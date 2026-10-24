"""Imagens dos perfis (banners).

Política de licença (resumo; detalhes em assets/README.md):
  • Nenhuma imagem da Wube é embutida no repositório ou no executável. O Presskit oficial (https://factorio.com/presskit)
    diz "You are welcome to use any of the assets, screenshots, and artwork, that you can find on our website", mas os
    Termos de Serviço proíbem redistribuir assets de arte. Por isso as capturas oficiais são baixadas do CDN da Wube
    para o cache LOCAL do usuário, sob ação explícita ("Baixar banners oficiais"), e nunca por hotlinking contínuo.
  • Sem as imagens oficiais, a interface usa banners industriais desenhados pelo próprio launcher.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import httpx

from .. import __version__, paths
from ..persistence.jsonstore import atomic_write_text, load_json, save_json

CDN = "https://cdn.factorio.com/assets/img"
SITE = "https://factorio.com"
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_CUSTOM_BYTES = 30 * 1024 * 1024
BANNER_W, THUMB_W = 1280, 480
ALLOWED_HOSTS = {"cdn.factorio.com", "factorio.com"}
LICENSE_NOTE = ("© Wube Software Ltd. Presskit (https://factorio.com/presskit): \"You are welcome to use any of the "
                "assets, screenshots, and artwork, that you can find on our website.\" Termos de Serviço: não é "
                "permitido redistribuir os assets de arte; por isso a imagem é baixada para o cache local do usuário "
                "e não é embutida no launcher.")
_ID_OK = re.compile(r"^[a-z0-9\-]+$")


@dataclass(frozen=True)
class OfficialImage:
    id: str
    title: str
    url: str
    page: str          # página oficial onde a imagem é publicada

    @property
    def group(self) -> str:
        return "Space Age" if self.id.startswith("sa-") else "Capturas de tela"


def _catalog() -> tuple[OfficialImage, ...]:
    items = [OfficialImage(f"screenshot-{n}", f"Captura {n}", f"{CDN}/screenshots/screenshot-{n}.jpg",
                           f"{SITE}/game/screenshots") for n in range(1, 35)]
    sa = [("aquilo", "Aquilo", f"{SITE}/static/img/content-space-age/space-age-aquilo.jpg", "/space-age/content"),
          ("enemies", "Inimigos do espaço", f"{SITE}/static/img/content-space-age/space-age-enemies.jpg", "/space-age/content"),
          ("banner", "Space Age", f"{SITE}/static/img/content-space-age/space-age-banner.jpg", "/space-age/content"),
          ("fulgora", "Fulgora", f"{CDN}/blog/fff-418-fulgora.png", "/space-age/content"),
          ("gleba", "Gleba", f"{CDN}/blog/fff-418-gleba.png", "/space-age/content"),
          ("vulcanus", "Vulcanus", f"{CDN}/blog/fff-418-vulcanus.png", "/space-age/content"),
          ("platform", "Plataforma espacial", f"{CDN}/blog/fff-418-space-platform-1.png", "/space-age/content"),
          ("rails", "Trilhos elevados", f"{CDN}/blog/fff-418-elevated-rails.png", "/space-age/content")]
    items += [OfficialImage(f"sa-{i}", t, u, SITE + p) for i, t, u, p in sa]
    return tuple(items)


OFFICIAL = _catalog()
BY_ID = {i.id: i for i in OFFICIAL}


class AssetError(Exception):
    pass


class AssetService:
    def __init__(self, data_dir: Path | None = None, client: httpx.Client | None = None):
        self.root = (Path(data_dir) if data_dir else paths.data_dir()) / "assets"
        self.shots = self.root / "factorio" / "screenshots"
        self.thumbs = self.root / "factorio" / "thumbnails"
        self.launcher = self.root / "launcher" / "placeholders"
        self._client = client or httpx.Client(headers={"User-Agent": f"FactorioModpackLauncher/{__version__}"},
                                              timeout=httpx.Timeout(30, connect=10), follow_redirects=False)
        self._lock = threading.Lock()

    # ---------- consulta ----------
    def image_path(self, image_id: str) -> Path | None:
        if not _ID_OK.match(image_id) or image_id not in BY_ID:
            return None
        p = self.shots / f"{image_id}.jpg"
        return p if p.is_file() else None

    def thumb_path(self, image_id: str) -> Path | None:
        p = self.thumbs / f"{image_id}.jpg"
        return p if p.is_file() else None

    def downloaded(self) -> list[OfficialImage]:
        return [i for i in OFFICIAL if self.image_path(i.id)]

    def missing(self) -> list[OfficialImage]:
        return [i for i in OFFICIAL if not self.image_path(i.id)]

    def default_for(self, profile_id: str) -> str | None:
        """Banner padrão determinístico (por perfil) entre as capturas já baixadas; None se não houver nenhuma."""
        have = [i.id for i in self.downloaded() if i.id.startswith("screenshot-")] or [i.id for i in self.downloaded()]
        if not have:
            return None
        return have[int(hashlib.sha1(profile_id.encode()).hexdigest(), 16) % len(have)]

    # ---------- resolução do banner de um perfil ----------
    @staticmethod
    def custom_file(profile_root: Path) -> Path | None:
        for ext in ("jpg", "png"):
            f = profile_root / f"banner.{ext}"
            if f.is_file():
                return f
        return None

    def banner_file(self, banner: str, profile_id: str, profile_root: Path, thumb: bool = False) -> Path | None:
        """Arquivo de imagem do banner ('' = padrão, 'official:<id>', 'custom'). None → placeholder desenhado."""
        if banner == "custom":
            f = self.custom_file(profile_root)
            if f:
                return f
        if banner.startswith("official:"):
            iid = banner.split(":", 1)[1]
            p = (self.thumb_path(iid) if thumb else None) or self.image_path(iid)
            if p:
                return p
        if banner in ("", "custom") or banner.startswith("official:"):
            iid = self.default_for(profile_id)
            if iid:
                return (self.thumb_path(iid) if thumb else None) or self.image_path(iid)
        return None

    # ---------- importação de imagem do usuário ----------
    def import_custom(self, profile_root: Path, src: Path) -> Path:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage, QImageReader

        try:
            size = src.stat().st_size
        except OSError as e:
            raise AssetError(f"Não foi possível ler o arquivo: {e}") from e
        if size > MAX_CUSTOM_BYTES:
            raise AssetError("Imagem grande demais (máximo 30 MB).")
        rd = QImageReader(str(src))
        rd.setAutoTransform(True)
        sz = rd.size()
        if not sz.isValid() or sz.width() < 64 or sz.height() < 32 or max(sz.width(), sz.height()) > 16000:
            raise AssetError("Arquivo não é uma imagem válida (ou tem dimensões fora do permitido).")
        if sz.width() > BANNER_W:
            rd.setScaledSize(sz.scaled(BANNER_W, 100000, Qt.KeepAspectRatio))
        img = rd.read()
        if img.isNull():
            raise AssetError(f"Falha ao decodificar a imagem: {rd.errorString()}")
        profile_root.mkdir(parents=True, exist_ok=True)
        has_alpha = img.hasAlphaChannel()
        dest = profile_root / ("banner.png" if has_alpha else "banner.jpg")
        tmp = dest.with_name(dest.name + ".part")
        ok = img.save(str(tmp), "PNG" if has_alpha else "JPG", -1 if has_alpha else 88)
        if not ok:
            tmp.unlink(missing_ok=True)
            raise AssetError("Falha ao gravar o banner.")
        for old in (profile_root / "banner.jpg", profile_root / "banner.png"):
            if old != dest:
                old.unlink(missing_ok=True)
        tmp.replace(dest)
        return dest

    @staticmethod
    def remove_custom(profile_root: Path) -> None:
        for ext in ("jpg", "png"):
            (profile_root / f"banner.{ext}").unlink(missing_ok=True)

    # ---------- download das imagens oficiais ----------
    def _fetch(self, url: str) -> bytes:
        if urlsplit(url).scheme != "https" or (urlsplit(url).hostname or "") not in ALLOWED_HOSTS:
            raise AssetError("URL fora dos hosts oficiais.")
        r = self._client.get(url)
        if r.status_code != 200:
            raise AssetError(f"HTTP {r.status_code}")
        if not r.headers.get("content-type", "").startswith("image/"):
            raise AssetError("resposta não é imagem")
        if len(r.content) > MAX_IMAGE_BYTES:
            raise AssetError("imagem acima do limite")
        return r.content

    def download_official(self, progress: Callable[[int, int, str], None] | None = None,
                          cancel: threading.Event | None = None, only: list[str] | None = None,
                          delay: float = 0.25) -> tuple[int, list[str]]:
        """Baixa as imagens oficiais que faltam (otimizando para 1280 px + miniatura 480 px). Retorna (baixadas, erros)."""
        from PySide6.QtCore import QBuffer, QIODevice, Qt
        from PySide6.QtGui import QImage

        todo = [i for i in OFFICIAL if (only is None or i.id in only) and not self.image_path(i.id)]
        errors: list[str] = []
        done = 0
        for n, item in enumerate(todo, 1):
            if cancel and cancel.is_set():
                break
            if progress:
                progress(n - 1, len(todo), item.title)
            try:
                data = self._fetch(item.url)
                img = QImage.fromData(data)
                if img.isNull():
                    raise AssetError("imagem ilegível")
                full = img if img.width() <= BANNER_W else img.scaledToWidth(BANNER_W, Qt.SmoothTransformation)
                thumb = full.scaledToWidth(THUMB_W, Qt.SmoothTransformation) if full.width() > THUMB_W else full
                self.shots.mkdir(parents=True, exist_ok=True)
                self.thumbs.mkdir(parents=True, exist_ok=True)
                for im, folder, q in ((full, self.shots, 86), (thumb, self.thumbs, 82)):
                    dest = folder / f"{item.id}.jpg"
                    tmp = dest.with_name(dest.name + ".part")
                    if not im.convertToFormat(QImage.Format_RGB888).save(str(tmp), "JPG", q):
                        raise AssetError("falha ao gravar")
                    tmp.replace(dest)
                done += 1
            except (AssetError, httpx.HTTPError, OSError) as e:
                errors.append(f"{item.title}: {e}")
            time.sleep(delay)
        if progress:
            progress(len(todo), len(todo), "")
        self.write_manifest()
        return done, errors

    # ---------- manifesto ----------
    def manifest(self) -> dict:
        items = []
        for i in OFFICIAL:
            p = self.image_path(i.id)
            items.append({"name": i.title, "id": i.id, "local_path": str(p) if p else None,
                          "thumbnail_path": str(self.thumb_path(i.id)) if self.thumb_path(i.id) else None,
                          "url": i.url, "source": i.page, "author": "Wube Software Ltd.", "license": LICENSE_NOTE,
                          "purpose": "Banner de perfil (Biblioteca)",
                          "sha256": hashlib.sha256(p.read_bytes()).hexdigest() if p else None,
                          "bundled_in_launcher": False})
        return {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "images": items}

    def write_manifest(self) -> Path:
        dest = self.root / "manifest.json"
        save_json(dest, self.manifest(), backup=False)
        return dest
