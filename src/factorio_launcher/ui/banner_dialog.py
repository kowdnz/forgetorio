"""Escolha do banner do perfil: imagens oficiais (baixadas sob demanda), imagem do computador ou padrão."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar,
                               QPushButton, QVBoxLayout, QWidget)

from ..models.entities import Profile
from ..services import asset_service as A
from ..services.profile_manager import ProfileError
from . import imagecache, tokens as T
from .common import error, info
from .workers import run_async


class _Progress(QObject):
    step = Signal(int, int, str)


class BannerDialog(QDialog):
    def __init__(self, ctx, parent: QWidget, p: Profile):
        super().__init__(parent)
        self.ctx, self.p = ctx, p
        self._cancel = threading.Event()
        self._prog = _Progress()
        self._prog.step.connect(self._on_step)
        self.setWindowTitle(f"Banner — {p.name}")
        self.resize(760, 560)
        lay = QVBoxLayout(self)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setObjectName("muted")
        lay.addWidget(self.hint)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(176, 99))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setSpacing(8)
        self.list.setWordWrap(True)
        self.list.setGridSize(QSize(196, 132))
        self.list.itemDoubleClicked.connect(lambda _: self._apply_selected())
        lay.addWidget(self.list, 1)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.status = QLabel()
        self.status.setObjectName("muted")
        lay.addWidget(self.status)
        row = QHBoxLayout()
        self.dl_btn = QPushButton("Baixar banners oficiais")
        self.dl_btn.clicked.connect(self._download)
        imp = QPushButton("Importar do computador…")
        imp.clicked.connect(self._import)
        reset = QPushButton("Restaurar padrão")
        reset.clicked.connect(self._reset)
        use = QPushButton("Usar selecionado")
        use.setObjectName("primary")
        use.clicked.connect(self._apply_selected)
        close = QPushButton("Fechar")
        close.clicked.connect(self.accept)
        for b in (self.dl_btn, imp, reset):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(use)
        row.addWidget(close)
        lay.addLayout(row)
        self._fill()

    # ---- conteúdo ----
    def _fill(self) -> None:
        a = self.ctx.pm.assets
        self.list.clear()
        cur = self.ctx.pm.get_profile(self.p.id) or self.p
        self.p = cur
        have = a.downloaded()
        missing = len(a.missing())
        self.hint.setText(
            "Imagens oficiais do Factorio (© Wube Software) são baixadas do site oficial para o cache local deste PC — "
            "elas não vêm embutidas no launcher. Você também pode importar qualquer imagem sua."
            if missing else "Todas as imagens oficiais já estão no cache local.")
        self.dl_btn.setText(f"Baixar banners oficiais ({missing})" if missing else "Banners oficiais baixados ✔")
        self.dl_btn.setEnabled(bool(missing))
        item = QListWidgetItem("Padrão (automático)")
        item.setData(Qt.UserRole, "default")
        item.setIcon(QIcon(imagecache.placeholder_banner(cur.id, cur.color, 176, 99, 2.0)))
        self.list.addItem(item)
        custom = a.custom_file(self.ctx.pm.profile_root(cur.id))
        if custom:
            ci = QListWidgetItem("Sua imagem")
            ci.setData(Qt.UserRole, "custom")
            pm = imagecache.cover_pixmap(custom, 176, 99, 2.0)
            if pm:
                ci.setIcon(QIcon(pm))
            self.list.addItem(ci)
        for img in have:
            it = QListWidgetItem(img.title + ("  (Space Age)" if img.group == "Space Age" else ""))
            it.setData(Qt.UserRole, f"official:{img.id}")
            pm = imagecache.cover_pixmap(a.thumb_path(img.id) or a.image_path(img.id), 176, 99, 2.0)
            if pm:
                it.setIcon(QIcon(pm))
            it.setToolTip(f"{img.url}\n© Wube Software Ltd.")
            self.list.addItem(it)
            if cur.banner == it.data(Qt.UserRole):
                self.list.setCurrentItem(it)
        if not have:
            self.status.setText("Nenhuma imagem oficial no cache ainda. O banner padrão é um desenho industrial gerado pelo launcher.")
        else:
            self.status.setText(f"{len(have)} imagens oficiais disponíveis.")

    # ---- ações ----
    def _apply_selected(self) -> None:
        it = self.list.currentItem()
        if it is None:
            return
        key = it.data(Qt.UserRole)
        try:
            if key == "default":
                self.ctx.pm.reset_banner(self.p)
            elif key == "custom":
                self.p.banner = "custom"
                self.ctx.pm.save_profile(self.p)
            else:
                self.ctx.pm.set_official_banner(self.p, key.split(":", 1)[1])
        except ProfileError as e:
            error(self, "Banner", str(e))
            return
        self.status.setText("Banner aplicado ✔")

    def _import(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Escolha uma imagem", "", "Imagens (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not f:
            return
        try:
            self.ctx.pm.import_banner(self.p, Path(f))
        except ProfileError as e:
            error(self, "Importar banner", str(e))
            return
        self._fill()
        self.status.setText("Imagem importada e aplicada ✔")

    def _reset(self) -> None:
        self.ctx.pm.reset_banner(self.p)
        self._fill()
        self.status.setText("Banner padrão restaurado ✔ (a imagem importada, se havia, foi removida do perfil)")

    def _download(self) -> None:
        missing = self.ctx.pm.assets.missing()
        self.dl_btn.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setRange(0, max(1, len(missing)))
        self._cancel.clear()

        def work():
            return self.ctx.pm.assets.download_official(lambda n, t, title: self._prog.step.emit(n, t, title), self._cancel)

        def done(res):
            n, errs = res
            self.bar.setVisible(False)
            self._fill()
            self.status.setText(f"{n} imagem(ns) baixada(s)." + (f" {len(errs)} falharam." if errs else ""))
            if errs:
                info(self, "Alguns downloads falharam", "\n".join(errs[:12]))

        def failed(e):
            self.bar.setVisible(False)
            self.dl_btn.setEnabled(True)
            error(self, "Download das imagens", str(e))

        run_async(work, done, failed)

    def _on_step(self, n: int, total: int, title: str) -> None:
        self.bar.setMaximum(max(1, total))
        self.bar.setValue(n)
        self.status.setText(f"Baixando {title}…" if title else "Concluindo…")

    def done(self, r: int) -> None:
        self._cancel.set()
        super().done(r)
