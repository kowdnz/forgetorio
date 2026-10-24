"""Montagem de argumentos e execução do Factorio (subprocess sem shell)."""
from __future__ import annotations

import csv
import io
import logging
import subprocess
import time
from pathlib import Path

from ..models.entities import FactorioInstall, Profile, now_iso
from .install_detector import _steam_roots

log = logging.getLogger("fml.runner")


class LaunchError(Exception):
    pass


def build_args(install: FactorioInstall, mods_dir: Path, config_path: Path,
               extra: list[str] | None = None) -> list[str]:
    return [install.exe, "--mod-directory", str(mods_dir), "--config", str(config_path), *(extra or [])]


def steam_exe_for_install(install: FactorioInstall) -> Path | None:
    """Use a Steam para jogos instalados em uma de suas bibliotecas."""
    root = Path(install.path)
    if root.parent.name.lower() != "common" or root.parent.parent.name.lower() != "steamapps":
        return None
    for steam_root in _steam_roots():
        exe = steam_root / "steam.exe"
        if exe.is_file():
            return exe
    return None


class SteamGameProcess:
    """Adapta o jogo iniciado pela Steam à interface poll/wait usada pela UI."""

    def __init__(self, pid_lister, startup_timeout: float = 120):
        self._pid_lister = pid_lister
        self._deadline = time.monotonic() + startup_timeout
        self._game_pid: int | None = None
        self._started_at: float | None = None
        self._exit_code: int | None = None

    def poll(self) -> int | None:
        if self._exit_code is not None:
            return self._exit_code
        pids = self._pid_lister()
        if self._game_pid is None:
            if pids:
                self._game_pid = pids[0]
                self._started_at = time.monotonic()
            elif time.monotonic() >= self._deadline:
                self._exit_code = 1
        elif self._game_pid not in pids:
            self._exit_code = 0
        return self._exit_code

    def elapsed_seconds(self) -> int:
        return int(time.monotonic() - self._started_at) if self._started_at is not None else 0

    def wait(self) -> int:
        while (code := self.poll()) is None:
            time.sleep(1)
        return code


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
        self._launched: dict[str, subprocess.Popen | SteamGameProcess] = {}   # profile_id -> processo

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
               extra: list[str] | None = None) -> subprocess.Popen | SteamGameProcess:
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
        steam_exe = steam_exe_for_install(install)
        if steam_exe:
            args = [str(steam_exe), "-applaunch", "427520", *args[1:]]
        log.info("Iniciando perfil %s: %s", profile.name, args)
        try:
            proc = self._popen(args, shell=False, cwd=str(steam_exe.parent if steam_exe else Path(install.exe).parent))
        except OSError as e:
            raise LaunchError(f"Falha ao iniciar o Factorio: {e}") from e
        if steam_exe:
            proc = SteamGameProcess(self._pid_lister)
        self._launched[profile.id] = proc
        profile.last_played = now_iso()
        return proc
