"""Montagem de argumentos e execução do Factorio (subprocess sem shell)."""
from __future__ import annotations

import csv
import io
import logging
import subprocess
from pathlib import Path

from ..models.entities import FactorioInstall, Profile, now_iso

log = logging.getLogger("fml.runner")


class LaunchError(Exception):
    pass


def build_args(install: FactorioInstall, mods_dir: Path, config_path: Path,
               extra: list[str] | None = None) -> list[str]:
    return [install.exe, "--mod-directory", str(mods_dir), "--config", str(config_path), *(extra or [])]


def running_factorio_pids() -> list[int]:
    """PIDs de factorio.exe em execução (qualquer origem). Vazio se não for possível consultar."""
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq factorio.exe", "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, shell=False, timeout=10,
                           encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return []
    pids = []
    for row in csv.reader(io.StringIO(r.stdout)):
        if len(row) > 1 and row[0].lower() == "factorio.exe":
            try:
                pids.append(int(row[1]))
            except ValueError:
                pass
    return pids


class GameRunner:
    def __init__(self, pid_lister=running_factorio_pids, popen=subprocess.Popen):
        self._pid_lister = pid_lister
        self._popen = popen
        self._launched: dict[str, subprocess.Popen] = {}   # profile_id -> processo

    def is_profile_running(self, profile_id: str) -> bool:
        p = self._launched.get(profile_id)
        if p is None:
            return False
        if p.poll() is None:
            return True
        del self._launched[profile_id]
        return False

    def any_running(self) -> bool:
        return bool(self._pid_lister())

    def launch(self, profile: Profile, install: FactorioInstall, mods_dir: Path, config_path: Path,
               extra: list[str] | None = None) -> subprocess.Popen:
        if not Path(install.exe).is_file():
            raise LaunchError(f"Executável não encontrado: {install.exe}")
        if not config_path.is_file():
            raise LaunchError("config.ini do perfil não existe; reabra o perfil para regenerar.")
        if not mods_dir.is_dir():
            raise LaunchError("Pasta de mods do perfil não existe.")
        if self.any_running():
            raise LaunchError("O Factorio já está em execução. Feche-o antes de iniciar outro perfil "
                              "(duas instâncias compartilhando dados podem corromper saves).")
        args = build_args(install, mods_dir, config_path, [*profile.extra_args, *(extra or [])])
        log.info("Iniciando perfil %s: %s", profile.name, args)
        try:
            proc = self._popen(args, shell=False, cwd=str(Path(install.exe).parent))
        except OSError as e:
            raise LaunchError(f"Falha ao iniciar o Factorio: {e}") from e
        self._launched[profile.id] = proc
        profile.last_played = now_iso()
        return proc
