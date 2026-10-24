"""JSON com schema_version, escrita atômica e backup (.bak)."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


class StoreError(Exception):
    pass


def atomic_write_text(path: Path, text: str, backup: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if backup and path.exists():
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_json(path: Path, data: dict[str, Any], backup: bool = True) -> None:
    payload = {"schema_version": SCHEMA_VERSION, **{k: v for k, v in data.items() if k != "schema_version"}}
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False), backup=backup)


def load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    """Lê JSON; se corrompido tenta o .bak; se ausente devolve default."""
    for candidate in (path, path.with_name(path.name + ".bak")):
        if candidate.exists():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                if data.get("schema_version", 1) > SCHEMA_VERSION:
                    raise StoreError(f"{path.name}: versão de schema mais nova que o app suporta")
                return data
    return dict(default) if default is not None else {}
