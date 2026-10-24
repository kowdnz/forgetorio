"""Credenciais do Mod Portal. Token fica no Windows Credential Manager (keyring) — nunca em JSON/log."""
from __future__ import annotations

import json
from pathlib import Path

from .. import paths

SERVICE = "FactorioModpackLauncher"


class AuthError(Exception):
    pass


class AuthStore:
    def __init__(self, backend=None):
        if backend is None:
            try:
                import keyring

                backend = keyring
            except Exception:  # keyring indisponível: sem persistência segura
                backend = None
        self._kr = backend
        self._memory: dict[str, str] = {}

    @property
    def secure_storage_available(self) -> bool:
        return self._kr is not None

    def save(self, username: str, token: str) -> None:
        if not username or not token:
            raise AuthError("Usuário e token são obrigatórios.")
        self._memory = {"u": username, "t": token}
        if self._kr is not None:
            try:
                self._kr.set_password(SERVICE, username, token)
                self._kr.set_password(SERVICE, "__last_user__", username)
            except Exception as e:
                raise AuthError(f"Não foi possível gravar no cofre do Windows: {type(e).__name__}") from e

    def load(self) -> tuple[str, str] | None:
        if self._memory:
            return self._memory["u"], self._memory["t"]
        if self._kr is None:
            return None
        try:
            user = self._kr.get_password(SERVICE, "__last_user__")
            token = self._kr.get_password(SERVICE, user) if user else None
        except Exception:
            return None
        return (user, token) if user and token else None

    def clear(self) -> None:
        creds = self.load()
        self._memory = {}
        if self._kr is not None and creds:
            for key in (creds[0], "__last_user__"):
                try:
                    self._kr.delete_password(SERVICE, key)
                except Exception:
                    pass

    def has_credentials(self) -> bool:
        return self.load() is not None


def read_player_data_credentials(player_data: Path | None = None) -> tuple[str, str] | None:
    """Lê service-username/service-token de player-data.json. Só deve ser chamado após ação explícita."""
    path = player_data or (paths.system_factorio_dir() / "player-data.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    user, token = data.get("service-username"), data.get("service-token")
    return (user, token) if isinstance(user, str) and isinstance(token, str) and user and token else None
