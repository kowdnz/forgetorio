"""Geração do config.ini por perfil. Nunca altera config.ini/config-path.cfg originais."""
from __future__ import annotations

import re
from pathlib import Path

from .. import paths
from ..models.entities import SAVE_EXCLUSIVE, FactorioInstall, Profile
from ..persistence.jsonstore import atomic_write_text

_SECTION = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_KEY = re.compile(r"^\s*;?\s*([A-Za-z0-9_\-]+)\s*=")

# Chaves que NUNCA são herdadas do config do sistema (caminhos são sempre gerados pelo launcher).
_FORCED = {"read-data", "write-data"}


def ini_path(p: Path) -> str:
    """Factorio aceita barras normais no Windows; evita problemas de escape."""
    return str(p).replace("\\", "/")


def shared_write_dir(profile: Profile) -> Path:
    return Path(profile.shared_dir) if profile.shared_dir else paths.system_factorio_dir()


def write_data_dir(profile: Profile, profile_root: Path) -> Path:
    if profile.save_mode == SAVE_EXCLUSIVE:
        return profile_root / "userdata"
    return shared_write_dir(profile)


def read_data_dir(install: FactorioInstall) -> Path:
    return Path(install.path) / "data"


def _template_lines(base_ini: Path | None) -> list[str]:
    """Usa o config.ini do sistema só como modelo de preferências (somente leitura)."""
    if base_ini and base_ini.is_file():
        try:
            return base_ini.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            pass
    return ["[general]", "locale=auto"]


def build_config(profile: Profile, install: FactorioInstall, profile_root: Path,
                 base_ini: Path | None = None, inherit_settings: bool = True) -> str:
    """Retorna o texto do config.ini do perfil.

    - [path] read-data -> <instalação>/data ; write-data -> userdata do perfil (exclusivo)
      ou diretório compartilhado (saves/blueprints/player-data comuns).
    - Demais seções são herdadas do config do sistema (idioma, gráficos, controles) quando permitido.
    """
    read_dir = ini_path(read_data_dir(install))
    write_dir = ini_path(write_data_dir(profile, profile_root))
    out: list[str] = ["; Gerado pelo Factorio Modpack Launcher — não edite a cópia original do jogo.",
                      "[path]", f"read-data={read_dir}", f"write-data={write_dir}", ""]
    if not inherit_settings:
        out += ["[general]", "locale=auto"]
        return "\n".join(out) + "\n"
    section = None
    skip_section = False
    for line in _template_lines(base_ini):
        m = _SECTION.match(line)
        if m:
            section = m.group(1).strip().lower()
            skip_section = section == "path"
            if not skip_section:
                out.append(line)
            continue
        if line.lstrip().startswith("; version=") or line.lstrip().startswith("; This is INI"):
            continue
        if skip_section:
            continue
        km = _KEY.match(line)
        if km and km.group(1) in _FORCED and not line.lstrip().startswith(";"):
            continue
        if section is None:
            continue  # cabeçalho/comentários antes da primeira seção
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


def write_profile_config(profile: Profile, install: FactorioInstall, profile_root: Path,
                         base_ini: Path | None = None, inherit_settings: bool = True) -> Path:
    cfg = profile_root / "config" / "config.ini"
    text = build_config(profile, install, profile_root, base_ini, inherit_settings)
    atomic_write_text(cfg, text, backup=True)
    if profile.save_mode == SAVE_EXCLUSIVE:
        (profile_root / "userdata" / "saves").mkdir(parents=True, exist_ok=True)
    return cfg


def parse_paths(config_text: str) -> dict[str, str]:
    """Utilitário (testes/diagnóstico): lê a seção [path]."""
    res, in_path = {}, False
    for line in config_text.splitlines():
        m = _SECTION.match(line)
        if m:
            in_path = m.group(1).strip().lower() == "path"
            continue
        if in_path and "=" in line and not line.lstrip().startswith(";"):
            k, v = line.split("=", 1)
            res[k.strip()] = v.strip()
    return res
