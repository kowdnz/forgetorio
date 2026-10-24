"""Detecção e validação de instalações do Factorio (Steam/standalone, qualquer disco)."""
from __future__ import annotations

import os
import re
import string
import subprocess
from pathlib import Path

from ..models.entities import FactorioInstall

EXE_REL = Path("bin") / "x64" / "factorio.exe"
_VERSION_RE = re.compile(r"Version:\s*(\d+\.\d+\.\d+)(?:\s*\(build\s*(\d+))?")
_VDF_PATH = re.compile(r'"path"\s+"([^"]+)"')


def _steam_roots() -> list[Path]:
    roots: list[Path] = []
    for env in ("ProgramFiles(x86)", "ProgramFiles"):
        v = os.environ.get(env)
        if v:
            roots.append(Path(v) / "Steam")
    try:
        import winreg  # type: ignore

        for hive, key, val in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        ):
            try:
                with winreg.OpenKey(hive, key) as k:
                    roots.append(Path(winreg.QueryValueEx(k, val)[0]))
            except OSError:
                pass
    except ImportError:
        pass
    return roots


def steam_library_dirs() -> list[Path]:
    libs: list[Path] = []
    for root in _steam_roots():
        libs.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        try:
            for m in _VDF_PATH.finditer(vdf.read_text(encoding="utf-8", errors="replace")):
                libs.append(Path(m.group(1).replace("\\\\", "\\")))
        except OSError:
            pass
    return libs


def candidate_paths() -> list[Path]:
    cands: list[Path] = []
    for lib in steam_library_dirs():
        cands.append(lib / "steamapps" / "common" / "Factorio")
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        v = os.environ.get(env)
        if v:
            cands.append(Path(v) / "Factorio")
    # bibliotecas Steam comuns em outros discos, mesmo que não estejam no vdf
    for letter in string.ascii_uppercase:
        drive = Path(f"{letter}:/")
        if drive.exists():
            for sub in ("SteamLibrary/steamapps/common/Factorio", "Steam/steamapps/common/Factorio",
                        "Games/Factorio", "Factorio"):
                cands.append(drive / sub)
    seen, out = set(), []
    for c in cands:
        key = os.path.normcase(str(c))
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def resolve_root(path: str | Path) -> Path | None:
    """Aceita a raiz do jogo, a pasta bin/x64 ou o próprio factorio.exe."""
    p = Path(path)
    if p.is_file() and p.name.lower() == "factorio.exe":
        p = p.parent.parent.parent
    for cand in (p, p.parent.parent if p.name.lower() == "x64" else p):
        if (cand / EXE_REL).is_file():
            return cand
    return None


def read_version(exe: Path, timeout: float = 20) -> tuple[str, str] | None:
    try:
        r = subprocess.run(
            [str(exe), "--version"], capture_output=True, text=True, timeout=timeout, shell=False,
            encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    m = _VERSION_RE.search(r.stdout or "")
    return (m.group(1), m.group(2) or "") if m else None


def validate_install(path: str | Path) -> FactorioInstall | None:
    root = resolve_root(path)
    if root is None:
        return None
    exe = root / EXE_REL
    ver = read_version(exe)
    if ver is None:
        return None
    return FactorioInstall.new(str(root), str(exe), ver[0], build=ver[1])


def detect_installs() -> list[FactorioInstall]:
    found: list[FactorioInstall] = []
    for c in candidate_paths():
        if (c / EXE_REL).is_file():
            inst = validate_install(c)
            if inst:
                found.append(inst)
    return found


def installed_dlcs(install: FactorioInstall) -> list[str]:
    data = Path(install.path) / "data"
    return [d for d in ("elevated-rails", "quality", "space-age") if (data / d / "info.json").is_file()]
