"""Snapshots de perfil (mods + mod-list + manifesto [+ saves exclusivos]) e restauração."""
from __future__ import annotations

import time
import zipfile
from pathlib import Path


class BackupError(Exception):
    pass


def _iter_files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file():
            yield p


def create_backup(profile_root: Path, include_saves: bool = False, label: str = "manual") -> Path:
    bdir = profile_root / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe = "".join(c for c in label if c.isalnum() or c in "-_")[:30] or "backup"
    dest = bdir / f"{stamp}-{safe}.zip"
    n = 1
    while dest.exists():
        dest = bdir / f"{stamp}-{safe}-{n}.zip"
        n += 1
    tmp = dest.with_name(dest.name + ".part")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            if (profile_root / "manifest.json").is_file():
                z.write(profile_root / "manifest.json", "manifest.json")
            for sub in ("mods", "config") + (("userdata/saves",) if include_saves else ()):
                base = profile_root / sub
                if base.is_dir():
                    for f in _iter_files(base):
                        z.write(f, f.relative_to(profile_root).as_posix())
        tmp.replace(dest)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise BackupError(f"Falha ao criar backup: {e}") from e
    return dest


def list_backups(profile_root: Path) -> list[Path]:
    bdir = profile_root / "backups"
    return sorted(bdir.glob("*.zip"), reverse=True) if bdir.is_dir() else []


def restore_backup(profile_root: Path, backup: Path, restore_saves: bool = False) -> Path:
    """Restaura mods/config (e saves se pedido). Antes cria um backup 'pre-restore' do estado atual."""
    if not zipfile.is_zipfile(backup):
        raise BackupError("Backup inválido")
    safety = create_backup(profile_root, include_saves=restore_saves, label="pre-restore")
    root = profile_root.resolve()
    with zipfile.ZipFile(backup) as z:
        members = []
        for zi in z.infolist():
            target = (root / zi.filename).resolve()
            if root not in target.parents and target != root:
                raise BackupError(f"Entrada insegura no backup: {zi.filename}")
            top = zi.filename.split("/")[0]
            if zi.is_dir() or top == "manifest.json":
                continue
            if top == "userdata" and not restore_saves:
                continue
            if top in ("mods", "config", "userdata"):
                members.append(zi)
        # troca limpa apenas das pastas presentes no backup
        for top in {m.filename.split("/")[0] for m in members if m.filename.split("/")[0] != "userdata"}:
            d = profile_root / top
            if d.is_dir():
                for f in _iter_files(d):
                    f.unlink()
        for m in members:
            dest = root / m.filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(m) as src, open(dest, "wb") as out:
                out.write(src.read())
    return safety
