"""Cliente do Mod Portal oficial (https://mods.factorio.com/api) + downloads seguros."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlsplit

import httpx

from .. import __version__, paths
from ..models.versions import parse_version
from ..persistence.jsonstore import load_json, save_json
from . import local_mods

log = logging.getLogger("fml.portal")

PORTAL = "https://mods.factorio.com"
USER_AGENT = f"FactorioModpackLauncher/{__version__} (+personal launcher)"
MAX_DOWNLOAD_BYTES = 2 * 1024**3
CATALOG_TTL = 24 * 3600
FULL_TTL = 3600
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_\- .'()]+$")


class PortalError(Exception):
    pass


class PortalOffline(PortalError):
    pass


class AuthRequired(PortalError):
    pass


class Cancelled(PortalError):
    pass


@dataclass
class Release:
    name: str
    version: str
    download_url: str
    file_name: str
    sha1: str
    factorio_version: str = ""
    dependencies: list[str] = field(default_factory=list)
    released_at: str = ""

    @staticmethod
    def from_api(name: str, d: dict) -> "Release":
        info = d.get("info_json") or {}
        return Release(name, str(d.get("version", "")), str(d.get("download_url", "")), str(d.get("file_name", "")),
                       str(d.get("sha1", "")), str(info.get("factorio_version", "")),
                       [x for x in info.get("dependencies", []) if isinstance(x, str)] if "dependencies" in info else ["base"],
                       str(d.get("released_at", "")))


def game_compat(mod_factorio_version: str, game_version: str) -> str:
    """'ok' (mesmo major.minor), 'maybe' (mesmo major, mod mais antigo) ou 'no'."""
    m, g = parse_version(mod_factorio_version), parse_version(game_version)
    if not m or not g:
        return "maybe"
    if m[:2] == g[:2]:
        return "ok"
    if m[0] == g[0] and m[1] < g[1]:
        return "maybe"
    return "no"


def redact_url(url: str) -> str:
    return re.sub(r"(token|username)=[^&]+", r"\1=***", url)


def allowed_download_host(url: str) -> bool:
    s = urlsplit(url)
    host = (s.hostname or "").lower()
    return s.scheme == "https" and (host == "factorio.com" or host.endswith(".factorio.com"))


class RateLimiter:
    def __init__(self, min_interval: float = 0.25):
        self.min_interval = min_interval
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            delta = time.monotonic() - self._last
            if delta < self.min_interval:
                time.sleep(self.min_interval - delta)
            self._last = time.monotonic()


class PortalClient:
    def __init__(self, cache_dir: Path | None = None, client: httpx.Client | None = None,
                 min_interval: float = 0.25, retries: int = 3, backoff: float = 0.8):
        self.cache_dir = Path(cache_dir) if cache_dir else paths.cache_dir()
        self._client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=httpx.Timeout(30, connect=10),
                                              follow_redirects=False)
        self._limiter = RateLimiter(min_interval)
        self._retries, self._backoff = retries, backoff
        self._full: dict[str, tuple[float, dict]] = {}
        self._catalog: list[dict] | None = None
        self._search_cache: dict[str, tuple[float, list[dict]]] = {}
        self._tag_count_cache: dict[str, int] = {}

    # ---------- HTTP ----------
    def _get_json(self, path: str, params: dict | None = None) -> dict:
        url = PORTAL + path
        last: Exception | None = None
        for attempt in range(self._retries):
            self._limiter.wait()
            try:
                r = self._client.get(url, params=params)
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
                last = e
                time.sleep(self._backoff * (attempt + 1))
                continue
            except httpx.HTTPError as e:
                raise PortalError(f"Erro de rede: {type(e).__name__}") from e
            if r.status_code == 404:
                raise PortalError("Mod não encontrado no Portal.")
            if r.status_code in (429, 500, 502, 503, 504):
                last = PortalError(f"HTTP {r.status_code}")
                time.sleep(self._backoff * (attempt + 1))
                continue
            if r.status_code != 200:
                raise PortalError(f"O Portal respondeu HTTP {r.status_code}.")
            try:
                data = r.json()
            except ValueError as e:
                raise PortalError("Resposta inválida do Portal.") from e
            if not isinstance(data, dict):
                raise PortalError("Resposta inesperada do Portal.")
            return data
        if isinstance(last, (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError)):
            raise PortalOffline("Sem conexão com o Mod Portal.") from last
        raise PortalError(f"Mod Portal indisponível ({last}).")

    def _post_json(self, path: str, body: dict) -> dict:
        """POST com o mesmo tratamento de retry/offline. O corpo (que contém o token) nunca é logado."""
        url = PORTAL + path
        last: Exception | None = None
        for attempt in range(self._retries):
            self._limiter.wait()
            try:
                r = self._client.post(url, json=body)
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
                last = e
                time.sleep(self._backoff * (attempt + 1))
                continue
            except httpx.HTTPError as e:
                raise PortalError(f"Erro de rede: {type(e).__name__}") from e
            if r.status_code in (401, 403):
                raise AuthRequired("O Portal recusou as credenciais (usuário/token inválidos).")
            if r.status_code == 400:
                try:
                    msg = str(r.json().get("message", ""))[:300]
                except ValueError:
                    msg = ""
                raise PortalError(f"Busca recusada pelo Portal: {msg}")
            if r.status_code in (429, 500, 502, 503, 504):
                last = PortalError(f"HTTP {r.status_code}")
                time.sleep(self._backoff * (attempt + 1))
                continue
            if r.status_code != 200:
                raise PortalError(f"O Portal respondeu HTTP {r.status_code}.")
            try:
                data = r.json()
            except ValueError as e:
                raise PortalError("Resposta inválida do Portal.") from e
            if not isinstance(data, dict):
                raise PortalError("Resposta inesperada do Portal.")
            return data
        if isinstance(last, (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError)):
            raise PortalOffline("Sem conexão com o Mod Portal.") from last
        raise PortalError(f"Mod Portal indisponível ({last}).")

    # ---------- busca oficial (POST /api/search; exige usuário + token) ----------
    SORTS = {"relevance": "relevancy", "downloads": "most_downloads", "updated": "last_updated_at",
             "trending": "trending"}

    @staticmethod
    def normalize_search_entry(m: dict) -> dict:
        lr = m.get("latest_release") if isinstance(m.get("latest_release"), dict) else {}
        fvs = [v for v in m.get("factorio_versions", []) if isinstance(v, str)]
        return {"name": m.get("name", ""), "title": m.get("title", ""), "owner": m.get("owner", ""),
                "summary": m.get("summary", ""), "downloads": m.get("downloads_count", 0),
                "category": m.get("category", ""),
                "version": m.get("latest_release_version") or lr.get("version", ""),
                "fv": fvs[0] if fvs else "", "fvs": fvs, "score": 0,
                "at": m.get("updated_at") or lr.get("released_at", ""),
                "tags": [t for t in m.get("tags", []) if isinstance(t, str)], "thumb": m.get("thumbnail", ""),
                "space_age": bool(m.get("requires_space_age"))}

    def search_api(self, credentials: tuple[str, str], *, query: str = "", tags: list[str] | None = None,
                   exclude_tags: list[str] | None = None, categories: list[str] | None = None,
                   sort: str = "relevance", version: str | None = None, show_deprecated: bool = False,
                   page: int = 1, page_size: int = 20) -> tuple[list[dict], int]:
        """Uma página da busca oficial. Várias `tags` formam UNIÃO (OR) no servidor — ver `search_api_all`."""
        if not credentials:
            raise AuthRequired("A busca por tags exige usuário e token do Mod Portal.")
        body: dict = {"username": credentials[0], "token": credentials[1], "page": page, "page_size": page_size,
                      "sort_attribute": self.SORTS.get(sort, "relevancy"), "show_deprecated": show_deprecated}
        if query.strip():
            body["query"] = query.strip()
        if version:
            body["version"] = version
        for key, val in (("tag", tags), ("exclude_tag", exclude_tags), ("category", categories)):
            if val:
                body[key] = list(val)
        d = self._post_json("/api/search", body)
        pg = d.get("pagination", {}) if isinstance(d.get("pagination"), dict) else {}
        return ([self.normalize_search_entry(m) for m in d.get("results", []) if isinstance(m, dict)],
                int(pg.get("count", 0)))

    def search_api_all(self, credentials: tuple[str, str], *, require_all_tags: bool = True, **kw) -> list[dict]:
        """Todos os resultados (um único request grande). Com `require_all_tags`, aplica AND localmente:
        o servidor devolve a união das tags, e o campo `tags` de cada resultado permite exigir todas."""
        key = json.dumps(kw, sort_keys=True, default=list) + str(require_all_tags)
        hit = self._search_cache.get(key)
        if hit and time.time() - hit[0] < 600:
            return hit[1]
        items, _ = self.search_api(credentials, page=1, page_size=20000, **kw)
        want = set(kw.get("tags") or [])
        if require_all_tags and len(want) > 1:
            items = [m for m in items if want <= set(m["tags"])]
        self._search_cache[key] = (time.time(), items)
        if len(self._search_cache) > 6:
            self._search_cache.pop(next(iter(self._search_cache)))
        return items

    def tag_counts(self, credentials: tuple[str, str], tag_ids: list[str], version: str | None,
                   show_deprecated: bool) -> dict[str, int]:
        out = {}
        for t in tag_ids:
            key = f"{version}|{show_deprecated}|{t}"
            if key not in self._tag_count_cache:
                self._tag_count_cache[key] = self.search_api(credentials, tags=[t], version=version,
                                                             show_deprecated=show_deprecated, page_size=1)[1]
            out[t] = self._tag_count_cache[key]
        return out

    # ---------- consulta ----------
    def list_page(self, page: int = 1, page_size: int = 25, sort: str = "downloads_count", sort_order: str = "desc",
                  version: str | None = None, hide_deprecated: bool = True) -> tuple[list[dict], int]:
        params: dict = {"page": page, "page_size": page_size, "sort": sort, "sort_order": sort_order,
                        "hide_deprecated": str(hide_deprecated).lower()}
        if version:
            params["version"] = version
        d = self._get_json("/api/mods", params)
        return d.get("results", []), int(d.get("pagination", {}).get("page_count", 1))

    def get_full(self, name: str, force: bool = False) -> dict:
        if not _SAFE_NAME.match(name):
            raise PortalError("Nome de mod inválido.")
        hit = self._full.get(name)
        if hit and not force and time.time() - hit[0] < FULL_TTL:
            return hit[1]
        path = self.cache_dir / "portal" / f"{name}.json"
        try:
            data = self._get_json(f"/api/mods/{quote(name)}/full")
        except PortalOffline:
            cached = load_json(path)
            if cached.get("data"):  # offline: usa cache do disco, sem enganar (a UI recebe a flag)
                d = cached["data"]
                d["_from_cache"] = True
                return d
            raise
        self._full[name] = (time.time(), data)
        try:
            save_json(path, {"data": data}, backup=False)
        except OSError:
            pass
        return data

    def releases(self, name: str) -> list[Release]:
        d = self.get_full(name)
        rels = [Release.from_api(name, r) for r in d.get("releases", []) if isinstance(r, dict)]
        rels.sort(key=lambda r: parse_version(r.version) or (0, 0, 0))
        return rels

    # ---------- catálogo (busca) ----------
    @property
    def catalog_file(self) -> Path:
        return self.cache_dir / "catalog.json"

    def catalog_age(self) -> float | None:
        data = load_json(self.catalog_file)
        return time.time() - data["fetched_at"] if "fetched_at" in data else None

    def load_catalog(self) -> list[dict]:
        if self._catalog is None:
            self._catalog = load_json(self.catalog_file).get("mods", [])
        return self._catalog

    def refresh_catalog(self) -> int:
        d = self._get_json("/api/mods", {"page_size": "max", "hide_deprecated": "true"})
        mods = []
        for m in d.get("results", []):
            lr = m.get("latest_release") or {}
            mods.append({"name": m.get("name", ""), "title": m.get("title", ""), "owner": m.get("owner", ""),
                         "summary": m.get("summary", ""), "downloads": m.get("downloads_count", 0),
                         "category": m.get("category", ""), "version": lr.get("version", ""),
                         "fv": (lr.get("info_json") or {}).get("factorio_version", ""), "score": m.get("score", 0),
                         "at": lr.get("released_at", "")})
        save_json(self.catalog_file, {"fetched_at": time.time(), "mods": mods}, backup=False)
        self._catalog = mods
        return len(mods)

    def search(self, query: str = "", game_version: str | None = None, category: str | None = None,
               limit: int = 200, sort: str = "relevance") -> list[dict]:
        terms = [t for t in query.lower().split() if t]
        out = []
        for m in self.load_catalog():
            if category and m["category"] != category:
                continue
            if game_version and game_compat(m["fv"], game_version) == "no":
                continue
            hay = f"{m['name']} {m['title']} {m['owner']} {m['summary']}".lower()
            if all(t in hay for t in terms):
                out.append(m)
        if sort == "downloads":
            out.sort(key=lambda m: -m["downloads"])
        elif sort == "updated":
            out.sort(key=lambda m: m.get("at", ""), reverse=True)
        elif sort == "name":
            out.sort(key=lambda m: (m["title"] or m["name"]).lower())
        else:
            out.sort(key=lambda m: (not (terms and any(t in m["name"].lower() or t in m["title"].lower() for t in terms)),
                                    -m["downloads"]))
        return out[:limit]

    # ---------- miniaturas ----------
    ASSETS = "https://assets-mod.factorio.com"

    def thumbnail(self, name: str, rel: str | None = None) -> Path | None:
        """Miniatura do mod em cache (baixa uma vez). `rel` (vindo da busca) evita consultar /full."""
        dest = self.cache_dir / "thumbs" / f"{name}.png"
        if dest.is_file():
            return dest
        if not rel:
            try:
                rel = self.get_full(name).get("thumbnail")
            except PortalError:
                return None
        if not isinstance(rel, str) or not re.fullmatch(r"/assets/[0-9a-f]+\.thumb\.png", rel):
            return None
        try:
            self._limiter.wait()
            r = self._client.get(self.ASSETS + rel)
            if r.status_code != 200 or len(r.content) > 2_000_000:
                return None
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".part")
            tmp.write_bytes(r.content)
            tmp.replace(dest)
            return dest
        except (httpx.HTTPError, OSError):
            return None

    # ---------- download ----------
    def mod_cache_path(self, release: Release) -> Path:
        return self.cache_dir / "mods" / release.name / f"{release.version}_{release.sha1[:12]}.zip"

    def download(self, release: Release, credentials: tuple[str, str] | None,
                 progress: Callable[[int, int], None] | None = None,
                 cancel: threading.Event | None = None) -> Path:
        """Baixa para cache/mods/<nome>/<versão>_<sha1>.zip (via .part), validando SHA-1 e estrutura."""
        dest = self.mod_cache_path(release)
        if dest.is_file() and _sha1(dest) == release.sha1.lower():
            if progress:
                progress(1, 1)
            return dest
        if not credentials:
            raise AuthRequired("Download requer autenticação do Mod Portal (usuário + token).")
        if not release.sha1 or not re.fullmatch(r"[0-9a-fA-F]{40}", release.sha1):
            raise PortalError("O Portal não informou SHA-1 válido para esta versão.")
        if not release.download_url.startswith("/download/"):
            raise PortalError("URL de download inesperada.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        url = PORTAL + release.download_url
        params: dict | None = {"username": credentials[0], "token": credentials[1]}
        try:
            for _hop in range(6):
                if not allowed_download_host(url):
                    raise PortalError("Redirecionamento para host não autorizado; download abortado.")
                self._limiter.wait()
                with self._client.stream("GET", url, params=params) as r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        url = str(r.headers.get("location", ""))
                        if url.startswith("/"):
                            url = PORTAL + url
                        params = None  # NUNCA reenviar credenciais após o redirecionamento
                        continue
                    if r.status_code in (401, 403):
                        raise AuthRequired("O Portal recusou as credenciais (usuário/token inválidos ou sem permissão).")
                    if r.status_code != 200:
                        raise PortalError(f"Download falhou: HTTP {r.status_code}.")
                    total = int(r.headers.get("content-length") or 0)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise PortalError("Arquivo maior que o limite permitido.")
                    sha, got = hashlib.sha1(), 0
                    with open(part, "wb") as f:
                        for chunk in r.iter_bytes(65536):
                            if cancel and cancel.is_set():
                                raise Cancelled("Download cancelado.")
                            got += len(chunk)
                            if got > MAX_DOWNLOAD_BYTES:
                                raise PortalError("Arquivo maior que o limite permitido.")
                            sha.update(chunk)
                            f.write(chunk)
                            if progress:
                                progress(got, total)
                    if total and got != total:
                        raise PortalError("Download interrompido (tamanho incompleto).")
                    if sha.hexdigest() != release.sha1.lower():
                        raise PortalError("SHA-1 não confere com o informado pelo Portal; arquivo descartado.")
                    break
            else:
                raise PortalError("Redirecionamentos demais.")
            try:
                info = local_mods.read_zip_info(part)
            except local_mods.ModError as e:
                raise PortalError(f"ZIP baixado é inválido: {e}") from e
            if info["name"] != release.name or info["version"] != release.version:
                raise PortalError("O ZIP baixado não corresponde ao mod/versão solicitados.")
            part.replace(dest)
            return dest
        except httpx.HTTPError as e:
            raise PortalOffline(f"Falha de rede durante o download: {type(e).__name__}") from e
        finally:
            part.unlink(missing_ok=True)


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_from_cache(cached: Path, mods_dir: Path) -> Path:
    """Copia (não vincula) o ZIP do cache global para o perfil: nenhum arquivo mutável é compartilhado."""
    info = local_mods.read_zip_info(cached)
    mods_dir.mkdir(parents=True, exist_ok=True)
    dest = mods_dir / local_mods.mod_filename(info["name"], info["version"])
    tmp = dest.with_name(dest.name + ".part")
    shutil.copyfile(cached, tmp)
    tmp.replace(dest)
    return dest
