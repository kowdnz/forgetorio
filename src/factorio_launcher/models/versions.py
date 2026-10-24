"""Versões do Factorio/mods (a.b.c) e sintaxe oficial de dependências."""
from __future__ import annotations

import re
from dataclasses import dataclass

Version = tuple[int, int, int]

_VER = re.compile(r"^\s*(\d+)\.(\d+)(?:\.(\d+))?")


def parse_version(text: str | None) -> Version | None:
    if not text:
        return None
    m = _VER.match(str(text))
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def fmt_version(v: Version | None) -> str:
    return ".".join(map(str, v)) if v else "?"


BASE_MODS = ("base", "core", "elevated-rails", "quality", "space-age")
DLC_MODS = ("elevated-rails", "quality", "space-age")

_NAME_OK = re.compile(r"^[A-Za-z0-9_\-. '()]+$")
_DEP = re.compile(r"^(?:(?P<prefix>\(\?\)|!|\?|~)\s*)?(?P<name>[^<>=]+?)\s*(?:(?P<op><=|>=|<|>|=)\s*(?P<ver>\d+\.\d+(?:\.\d+)?))?\s*$")


@dataclass(frozen=True)
class Dependency:
    name: str
    kind: str  # required | optional | hidden_optional | incompatible | no_order
    op: str | None = None
    version: Version | None = None

    @property
    def is_required(self) -> bool:
        return self.kind == "required"

    def accepts(self, v: Version | None) -> bool:
        if self.op is None or self.version is None:
            return True
        if v is None:
            return False
        return {
            "<": v < self.version, "<=": v <= self.version, ">": v > self.version,
            ">=": v >= self.version, "=": v == self.version,
        }[self.op]

    def constraint_text(self) -> str:
        return f"{self.op} {fmt_version(self.version)}" if self.op else ""


_KINDS = {None: "required", "!": "incompatible", "?": "optional", "(?)": "hidden_optional", "~": "no_order"}


def parse_dependency(text: str) -> Dependency | None:
    m = _DEP.match(text or "")
    if not m:
        return None
    name = m.group("name").strip()
    if not _NAME_OK.match(name):
        return None
    return Dependency(name, _KINDS[m.group("prefix")], m.group("op"), parse_version(m.group("ver")))


def parse_dependencies(items: list[str] | None) -> list[Dependency]:
    out = []
    for item in items or []:
        if isinstance(item, str):
            d = parse_dependency(item)
            if d:
                out.append(d)
    return out


def mod_game_dependency(deps: list[Dependency]) -> Dependency | None:
    return next((d for d in deps if d.name == "base" and d.kind == "required"), None)
