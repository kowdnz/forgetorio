"""Ponto de entrada e contexto de serviços compartilhados pela UI."""
from __future__ import annotations

import sys
from pathlib import Path

from . import paths
from .logsetup import setup_logging
from .persistence.jsonstore import load_json, save_json
from .services.auth_store import AuthStore
from .services.download_manager import DownloadManager
from .services.game_runner import GameRunner
from .services.portal_client import PortalClient
from .services.profile_manager import ProfileManager


class AppContext:
    """Agrupa serviços. `notify_download` é substituído pela UI para repassar jobs à thread principal."""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else paths.data_dir()
        self.pm = ProfileManager(self.data_dir)
        self.runner = GameRunner()
        self.auth = AuthStore()
        self.portal = PortalClient(self.data_dir / "cache")
        self.notify_download = lambda job: None
        self.on_game_exit = lambda profile_id, seconds: None   # a janela principal conecta (thread-safe)
        self.downloads = DownloadManager(self.portal, self.auth.load, lambda j: self.notify_download(j))

    @property
    def _settings_file(self) -> Path:
        return self.data_dir / "settings.json"

    def settings(self) -> dict:
        return load_json(self._settings_file, {})

    def set_setting(self, key: str, value) -> None:
        s = self.settings()
        s[key] = value
        save_json(self._settings_file, s)


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .ui.main_window import MainWindow
    from .ui.theme import apply_theme

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Factorio Modpack Launcher")
    app.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / "assets" / "app.png")))
    apply_theme(app)
    ctx = AppContext()
    win = MainWindow(ctx)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
