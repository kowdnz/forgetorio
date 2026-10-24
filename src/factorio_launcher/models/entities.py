from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

SAVE_SHARED = "shared"
SAVE_EXCLUSIVE = "exclusive"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class FactorioInstall:
    id: str
    path: str          # pasta raiz do jogo (contém bin/ e data/)
    exe: str
    version: str
    label: str = ""
    build: str = ""

    @staticmethod
    def new(path: str, exe: str, version: str, label: str = "", build: str = "") -> "FactorioInstall":
        return FactorioInstall(str(uuid.uuid4()), path, exe, version, label or path, build)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "FactorioInstall":
        return FactorioInstall(d["id"], d["path"], d["exe"], d.get("version", "?"), d.get("label", ""), d.get("build", ""))


@dataclass
class Profile:
    id: str
    name: str
    install_id: str = ""
    save_mode: str = SAVE_EXCLUSIVE
    shared_dir: str = ""           # base de dados compartilhada; vazio => %APPDATA%/Factorio
    color: str = "#4f8cff"
    notes: str = ""
    dev_mode: bool = False
    pins: dict[str, str] = field(default_factory=dict)       # lockfile: mod -> versão fixada
    created_at: str = field(default_factory=now_iso)
    last_played: str = ""
    extra_args: list[str] = field(default_factory=list)
    banner: str = ""            # "" (padrão) | "official:<id>" | "custom" (arquivo banner.* na pasta do perfil)
    favorite: bool = False
    play_seconds: int = 0       # tempo jogado registrado pelo launcher (só sessões iniciadas por ele)

    @staticmethod
    def new(name: str, **kw: Any) -> "Profile":
        return Profile(id=str(uuid.uuid4()), name=name, **kw)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Profile":
        known = {k: v for k, v in d.items() if k in Profile.__dataclass_fields__}
        return Profile(**known)


@dataclass
class ModInfo:
    """Mod instalado no perfil (ZIP ou pasta)."""
    name: str
    version: str
    title: str = ""
    author: str = ""
    description: str = ""
    factorio_version: str = ""
    dependencies: list[str] = field(default_factory=list)
    filename: str = ""
    enabled: bool = True
    is_dir: bool = False
    pinned: bool = False
