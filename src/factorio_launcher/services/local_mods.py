"""Leitura segura de mods locais (ZIP/pasta) e gestão do mod-list.json de um perfil."""
from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath

from ..models.entities import ModInfo
from ..persistence.jsonstore import atomic_write_text

MAX_INFO_BYTES = 1_000_000
MAX_ZIP_ENTRIES = 200_000
MAX_ZIP_UNCOMPRESSED = 8 * 1024**3
MAX_ZIP_RATIO = 1000
_NAME_OK = re.compile(r"^[A-Za-z0-9_\- .'()]+$")
_VER_OK = re.compile(r"^\d+\.\d+\.\d+$")


class ModError(Exception):
    pass


def _unsafe_member(name: str) -> bool:
    n = name.replace("\\", "/")
    p = PurePosixPath(n)
    return n.startswith("/") or ".." in p.parts or (len(n) > 1 and n[1] == ":")


def _validate_info(info: dict) -> None:
    name, ver = info.get("name"), info.get("version")
    if not isinstance(name, str) or not _NAME_OK.match(name) or ".." in name or len(name) > 100:
        raise ModError("info.json: 'name' ausente ou inválido")
    if not isinstance(ver, str) or not _VER_OK.match(ver):
        raise ModError("info.json: 'version' ausente ou inválida (esperado X.Y.Z)")


def read_zip_info(zip_path: Path) -> dict:
    """Lê info.json de um ZIP sem extrair. Lança ModError em ZIP malformado/perigoso."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as e:
        raise ModError(f"ZIP inválido ou ilegível: {e}") from e
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise ModError("ZIP com entradas demais")
        total = 0
        for zi in infos:
            if _unsafe_member(zi.filename):
                raise ModError(f"ZIP contém caminho inseguro: {zi.filename!r}")
            total += zi.file_size
            if zi.file_size > 50_000_000 and zi.file_size / max(zi.compress_size, 1) > MAX_ZIP_RATIO:
                raise ModError("ZIP com taxa de compressão suspeita")
        if total > MAX_ZIP_UNCOMPRESSED:
            raise ModError("ZIP descompactado grande demais")
        cands = []
        for zi in infos:
            parts = PurePosixPath(zi.filename.replace("\\", "/")).parts
            if not zi.is_dir() and parts and parts[-1] == "info.json" and len(parts) <= 2:
                cands.append((len(parts), zi))
        if not cands:
            raise ModError("ZIP sem info.json na raiz da pasta do mod")
        zi = min(cands, key=lambda c: c[0])[1]
        if zi.file_size > MAX_INFO_BYTES:
            raise ModError("info.json grande demais")
        try:
            info = json.loads(zf.read(zi).decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError) as e:
            raise ModError(f"info.json malformado: {e}") from e
        if not isinstance(info, dict):
            raise ModError("info.json deve ser um objeto")
    _validate_info(info)
    return info


def read_zip_thumbnail(zip_path: Path, max_bytes: int = 2_000_000) -> bytes | None:
    """Lê o thumbnail.png do mod (se houver) sem extrair o ZIP. Entradas inseguras ou grandes são ignoradas."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for zi in zf.infolist():
                parts = PurePosixPath(zi.filename.replace("\\", "/")).parts
                if (not _unsafe_member(zi.filename) and len(parts) == 2 and parts[1].lower() == "thumbnail.png"
                        and 0 < zi.file_size <= max_bytes):
                    return zf.read(zi)
    except (zipfile.BadZipFile, OSError):
        pass
    return None


def read_dir_info(folder: Path) -> dict:
    f = folder / "info.json"
    try:
        if f.stat().st_size > MAX_INFO_BYTES:
            raise ModError("info.json grande demais")
        info = json.loads(f.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise ModError(f"info.json ilegível: {e}") from e
    if not isinstance(info, dict):
        raise ModError("info.json deve ser um objeto")
    _validate_info(info)
    return info


def to_modinfo(info: dict, filename: str, is_dir: bool = False) -> ModInfo:
    deps = info.get("dependencies")
    if not isinstance(deps, list):
        deps = ["base"]  # padrão do Factorio quando o campo é omitido
    return ModInfo(
        name=info["name"], version=info["version"], title=str(info.get("title", info["name"])),
        author=str(info.get("author", "")), description=str(info.get("description", "")),
        factorio_version=str(info.get("factorio_version", "")),
        dependencies=[d for d in deps if isinstance(d, str)], filename=filename, is_dir=is_dir)


def mod_filename(name: str, version: str) -> str:
    return f"{name}_{version}.zip"


# ---------- mod-list.json ----------

def mod_list_path(mods_dir: Path) -> Path:
    return mods_dir / "mod-list.json"


def read_mod_list(mods_dir: Path) -> dict[str, bool]:
    try:
        data = json.loads(mod_list_path(mods_dir).read_text(encoding="utf-8"))
        return {m["name"]: bool(m.get("enabled", True)) for m in data.get("mods", []) if "name" in m}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def write_mod_list(mods_dir: Path, states: dict[str, bool]) -> None:
    ordered = sorted(states, key=lambda n: (n != "base", n))
    payload = {"mods": [{"name": n, "enabled": states[n]} for n in ordered]}
    atomic_write_text(mod_list_path(mods_dir), json.dumps(payload, indent=2), backup=True)


def scan_mods(mods_dir: Path, pins: dict[str, str] | None = None) -> list[ModInfo]:
    """Mods do perfil (ZIPs e pastas com info.json). ZIPs inválidos são ignorados."""
    pins = pins or {}
    states = read_mod_list(mods_dir)
    out: list[ModInfo] = []
    if not mods_dir.is_dir():
        return out
    for p in sorted(mods_dir.iterdir(), key=lambda x: x.name.lower()):
        try:
            if p.is_file() and p.suffix.lower() == ".zip":
                mi = to_modinfo(read_zip_info(p), p.name)
            elif p.is_dir() and (p / "info.json").is_file():
                mi = to_modinfo(read_dir_info(p), p.name, is_dir=True)
            else:
                continue
        except ModError:
            continue
        mi.enabled = states.get(mi.name, True)
        mi.pinned = pins.get(mi.name) == mi.version
        out.append(mi)
    return out


def install_zip(src: Path, mods_dir: Path, overwrite: bool = False) -> ModInfo:
    """Copia (nunca move) um ZIP validado para a pasta de mods do perfil e o habilita."""
    info = read_zip_info(src)
    mods_dir.mkdir(parents=True, exist_ok=True)
    dest = mods_dir / mod_filename(info["name"], info["version"])
    if dest.resolve().parent != mods_dir.resolve():
        raise ModError("destino inválido")
    if dest.exists() and not overwrite:
        raise ModError(f"{dest.name} já está instalado neste perfil")
    tmp = dest.with_name(dest.name + ".part")
    try:
        shutil.copyfile(src, tmp)
        tmp.replace(dest)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise ModError(f"Falha ao gravar o mod: {e}") from e
    states = read_mod_list(mods_dir)
    states[info["name"]] = True
    write_mod_list(mods_dir, states)
    return to_modinfo(info, dest.name)


def install_folder(src: Path, mods_dir: Path) -> ModInfo:
    """Mod em desenvolvimento: copia a pasta como <name>_<version>/ (nunca altera a origem)."""
    info = read_dir_info(src)
    dest = mods_dir / f"{info['name']}_{info['version']}"
    if dest.exists():
        raise ModError(f"{dest.name} já existe neste perfil")
    shutil.copytree(src, dest)
    states = read_mod_list(mods_dir)
    states[info["name"]] = True
    write_mod_list(mods_dir, states)
    return to_modinfo(info, dest.name, is_dir=True)


def remove_mod(mods_dir: Path, mod: ModInfo) -> None:
    target = (mods_dir / mod.filename).resolve()
    if target.parent != mods_dir.resolve():
        raise ModError("caminho fora da pasta de mods")
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink(missing_ok=True)
    if not any(m.name == mod.name for m in scan_mods(mods_dir)):
        states = read_mod_list(mods_dir)
        states.pop(mod.name, None)
        write_mod_list(mods_dir, states)


def set_enabled(mods_dir: Path, name: str, enabled: bool) -> None:
    if name == "core":
        raise ModError("'core' não pode ser alterado")
    states = read_mod_list(mods_dir)
    states[name] = enabled
    write_mod_list(mods_dir, states)


def default_mod_list(dlcs: list[str]) -> dict[str, bool]:
    states = {"base": True}
    for d in ("elevated-rails", "quality", "space-age"):
        states[d] = d in dlcs
    return states
