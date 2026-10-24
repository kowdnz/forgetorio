"""Diretórios do launcher. Nunca aponta para a instalação do jogo nem para %APPDATA%/Factorio."""
from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("FML_DATA_DIR")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "FactorioModpackLauncher"


def profiles_dir() -> Path:
    return data_dir() / "profiles"


def cache_dir() -> Path:
    return data_dir() / "cache"


def logs_dir() -> Path:
    return data_dir() / "logs"


def system_factorio_dir() -> Path:
    """%APPDATA%/Factorio — somente leitura (importação com consentimento)."""
    return Path(os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")) / "Factorio"
