"""Início do Factorio pela UI (valida, regenera config, inicia e mede o tempo de jogo)."""
from __future__ import annotations

import threading
import time

from PySide6.QtWidgets import QWidget

from ..models.entities import Profile
from ..services.game_runner import LaunchError, SteamGameProcess
from ..services.profile_manager import ProfileError
from .common import error

MIN_SESSION_SECONDS = 10   # ignora processos que terminam logo (ex.: o .exe relançando por outro caminho)


def launch_profile(ctx, parent: QWidget, p: Profile, extra: list[str] | None = None) -> bool:
    """Regenera o config.ini do perfil, valida e inicia o Factorio com --mod-directory/--config do perfil."""
    inst = ctx.pm.get_install(p.install_id)
    if inst is None:
        error(parent, "Jogar", "A instalação do Factorio deste perfil não está cadastrada. Vá em Configurações.")
        return False
    try:
        cfg = ctx.pm.regenerate_config(p)
        proc = ctx.runner.launch(p, inst, ctx.pm.mods_dir(p), cfg, extra)
        ctx.pm.save_profile(p)
    except (LaunchError, ProfileError, OSError) as e:
        error(parent, "Não foi possível iniciar", str(e))
        return False
    if proc is not None and hasattr(proc, "wait"):
        pid = p.id

        def watch() -> None:
            t0 = time.time()
            try:
                proc.wait()
            except Exception:  # noqa: BLE001
                return
            seconds = proc.elapsed_seconds() if isinstance(proc, SteamGameProcess) else int(time.time() - t0)
            ctx.on_game_exit(pid, seconds)

        threading.Thread(target=watch, daemon=True, name=f"play-{pid[:6]}").start()
    return True
