"""Lista (somente leitura) os saves que a Steam Cloud conhece para o Factorio (app 427520).

Fonte: Steam/userdata/<conta>/427520/remotecache.vdf. Nada é escrito, baixado ou movido: é apenas o inventário
da última sincronização feita pela própria Steam.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import install_detector

APP_ID = "427520"
_ENTRY = re.compile(r'"(Factorio/saves/[^"]+)"\s*\{([^}]*)\}')
_FIELD = re.compile(r'"(\w+)"\s+"([^"]*)"')


@dataclass
class CloudSave:
    name: str            # nome do arquivo, ex.: "meu save.zip"
    size: int
    mtime: int           # epoch (campo "time")
    account: str         # pasta da conta Steam
    synced: bool         # syncstate == 1


def parse_remotecache(text: str, account: str = "") -> list[CloudSave]:
    out = []
    for m in _ENTRY.finditer(text):
        fields = dict(_FIELD.findall(m.group(2)))
        name = m.group(1).split("/", 2)[2]
        if "/" in name:
            continue  # subpastas não são saves
        try:
            out.append(CloudSave(name, int(fields.get("size", 0)), int(fields.get("time", 0)), account,
                                 fields.get("syncstate") == "1"))
        except ValueError:
            continue
    return out


def userdata_roots() -> list[Path]:
    seen, out = set(), []
    for root in install_detector._steam_roots():
        ud = root / "userdata"
        key = str(ud).lower()
        if ud.is_dir() and key not in seen:
            seen.add(key)
            out.append(ud)
    return out


def list_cloud_saves(roots: list[Path] | None = None) -> list[CloudSave]:
    saves: list[CloudSave] = []
    for ud in roots if roots is not None else userdata_roots():
        try:
            accounts = [d for d in ud.iterdir() if d.is_dir()]
        except OSError:
            continue
        for acc in accounts:
            f = acc / APP_ID / "remotecache.vdf"
            try:
                saves += parse_remotecache(f.read_text(encoding="utf-8", errors="replace"), acc.name)
            except OSError:
                continue
    return sorted(saves, key=lambda s: s.mtime, reverse=True)
