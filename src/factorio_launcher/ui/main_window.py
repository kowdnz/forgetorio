from __future__ import annotations

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout,
                               QWidget)

from .. import __version__
from ..app import AppContext
from ..services.download_manager import QUEUED, RUNNING
from . import tokens as T
from .downloads_page import DownloadsPage
from .explore_page import ExplorePage
from .icons import icon, pixmap
from .library_page import LibraryPage
from .profile_page import ProfilePage
from .settings_page import SettingsPage


class _Bridge(QObject):
    download_changed = Signal(object)
    game_exited = Signal(str, int)


class NavButton(QPushButton):
    """Item da sidebar com ícone, destaque laranja quando ativo e selo de contagem (downloads)."""

    def __init__(self, icon_name: str, label: str):
        super().__init__("   " + label)
        self.icon_name = icon_name
        self.setObjectName("nav")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(20, 20))
        self.toggled.connect(lambda _: self._icon())
        self._icon()
        self.badge = QLabel(self)
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setStyleSheet(f"background:{T.BLUE}; color:white; border-radius:10px; font-size:{T.FS_XS}px; font-weight:700;")
        self.badge.setFixedSize(22, 20)
        self.badge.hide()

    def _icon(self) -> None:
        self.setIcon(icon(self.icon_name, T.ORANGE if self.isChecked() else T.TEXT_MUTED, 20))

    def set_badge(self, n: int) -> None:
        self.badge.setVisible(n > 0)
        self.badge.setText(str(n) if n < 100 else "99+")

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.badge.move(self.width() - 40, (self.height() - 20) // 2)


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle("Factorio Modpack Launcher")
        self.resize(1440, 860)
        self.setMinimumSize(900, 600)
        self.bridge = _Bridge()
        ctx.notify_download = self.bridge.download_changed.emit   # thread-safe: entrega na thread da UI
        ctx.on_game_exit = self.bridge.game_exited.emit

        self.stack = QStackedWidget()
        self.library = LibraryPage(ctx, self)
        self.profile_page = ProfilePage(ctx, self)
        self.explore = ExplorePage(ctx, self)
        self.downloads = DownloadsPage(ctx, self)
        self.settings = SettingsPage(ctx, self)
        for w in (self.library, self.profile_page, self.explore, self.downloads, self.settings):
            w.setObjectName("page")
            self.stack.addWidget(w)
        self.bridge.download_changed.connect(self.downloads.on_job)
        self.bridge.download_changed.connect(self.profile_page.on_job)
        self.bridge.download_changed.connect(lambda _j: self._update_badge())
        self.bridge.game_exited.connect(self.library.on_game_exit)

        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(T.SIDEBAR_W)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(2)
        brand = QWidget()
        bl = QHBoxLayout(brand)
        bl.setContentsMargins(18, 20, 14, 18)
        logo = QLabel()
        logo.setPixmap(pixmap("gear", T.ORANGE, 38))
        bl.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        a = QLabel("Factorio")
        a.setStyleSheet(f"font-size:{T.FS_LG + 1}px; font-weight:800; color:{T.ORANGE};")
        b = QLabel("Modpack Launcher")
        b.setStyleSheet(f"font-size:{T.FS_LG - 1}px; font-weight:600; color:{T.TEXT};")
        names.addWidget(a)
        names.addWidget(b)
        bl.addLayout(names)
        bl.addStretch()
        sl.addWidget(brand)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self._nav: dict[str, tuple[NavButton, QWidget]] = {}
        for key, label, ic, page in (("lib", "Biblioteca", "library", self.library),
                                     ("exp", "Explorar Mods", "explore", self.explore),
                                     ("dl", "Downloads", "download", self.downloads),
                                     ("cfg", "Configurações", "settings", self.settings)):
            btn = NavButton(ic, label)
            btn.clicked.connect(lambda _=False, pg=page: self.goto(pg))
            self.group.addButton(btn)
            sl.addWidget(btn)
            self._nav[key] = (btn, page)
        sl.addStretch()
        ver = QLabel(f"v{__version__}\nFeito para a comunidade Factorio")
        ver.setStyleSheet(f"color:{T.TEXT_MUTED}; font-size:{T.FS_XS}px;")
        ver.setContentsMargins(20, 8, 16, 16)
        sl.addWidget(ver)

        root = QWidget()
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(side)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.goto(self.library)

    def _update_badge(self) -> None:
        n = sum(1 for j in self.ctx.downloads.jobs if j.status in (QUEUED, RUNNING))
        self._nav["dl"][0].set_badge(n)

    def goto(self, page: QWidget) -> None:
        self.stack.setCurrentWidget(page)
        for b, p in self._nav.values():
            b.setChecked(p is page)
        if hasattr(page, "refresh"):
            page.refresh()
        self._update_badge()

    def open_profile(self, profile_id: str) -> None:
        self.profile_page.show_profile(profile_id)
        self.stack.setCurrentWidget(self.profile_page)
        for b, _ in self._nav.values():
            b.setChecked(False)
        self._nav["lib"][0].setChecked(True)   # a página de detalhes pertence à Biblioteca

    def explore_for(self, profile_id: str) -> None:
        self.explore.select_profile(profile_id)
        self.goto(self.explore)
