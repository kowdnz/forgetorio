"""Widgets reutilizáveis da Biblioteca: badges, interruptor, banner, estatística e card de perfil."""
from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRectF, QSize, Qt, Property, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from ..models.entities import SAVE_EXCLUSIVE, Profile
from . import imagecache, tokens as T
from .icons import icon, pixmap


# ---------- formatação ----------
def ago(ts: float | None) -> str:
    if not ts:
        return "nunca"
    s = max(0, time.time() - ts)
    for lim, div, unit in ((60, 1, "s"), (3600, 60, "min"), (86400, 3600, "h"), (86400 * 30, 86400, "dia(s)"),
                           (86400 * 365, 86400 * 30, "mês(es)"), (1e12, 86400 * 365, "ano(s)")):
        if s < lim:
            return "agora há pouco" if unit == "s" else f"há {max(int(s // div), 1)} {unit}"
    return "—"


def iso_to_ts(iso: str) -> float | None:
    try:
        return datetime.fromisoformat(iso).timestamp()
    except (ValueError, TypeError):
        return None


def fmt_playtime(seconds: int) -> str:
    if seconds <= 0:
        return "—"
    h, m = divmod(seconds // 60, 60)
    return f"{h}h" if h >= 10 else (f"{h}h {m:02d}min" if h else f"{m}min")


# ---------- peças ----------
class Badge(QLabel):
    def __init__(self, text: str, kind: str = "gray", icon_name: str | None = None):
        super().__init__()
        fg, bg, border = T.BADGE_STYLES[kind]
        self.setText(text)
        self.setStyleSheet(f"QLabel {{ color:{fg}; background:{bg}; border:1px solid {border}; border-radius:6px;"
                           f" padding:3px 7px 3px {23 if icon_name else 7}px; font-size:{T.FS_XS}px; font-weight:600; }}")
        self._icon = (icon_name, fg)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.adjustSize()

    def paintEvent(self, e) -> None:
        super().paintEvent(e)
        if self._icon[0]:
            p = QPainter(self)
            p.drawPixmap(7, (self.height() - 13) // 2, pixmap(self._icon[0], self._icon[1], 13))
            p.end()


class ElidedLabel(QLabel):
    """Texto que se abrevia no meio (bom para caminhos) e mostra o valor completo no tooltip."""

    def __init__(self, text: str = ""):
        super().__init__()
        self._full = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.set_full(text)

    def set_full(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._elide()

    def _elide(self) -> None:
        self.setText(self.fontMetrics().elidedText(self._full, Qt.ElideMiddle, max(20, self.width() - 4)))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._elide()


class IconButton(QToolButton):
    def __init__(self, name: str, tip: str = "", size: int = 18, color: str = T.TEXT, box: int = 34,
                 hover_color: str | None = None, flat: bool = False):
        super().__init__()
        self._name, self._size, self._color, self._hover = name, size, color, hover_color or T.ORANGE
        self.setIcon(icon(name, color, size))
        self.setIconSize(QSize(size, size))
        self.setFixedSize(box, box)
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"QToolButton {{ background:{'transparent' if flat else T.SURFACE}; border:{'none' if flat else '1px solid ' + T.BORDER};"
            f" border-radius:{T.RADIUS_MD}px; }} QToolButton:hover {{ border-color:{T.ORANGE}; background:{T.SURFACE_HOVER}; }}")

    def set_icon(self, name: str, color: str | None = None, **kw) -> None:
        self._name = name
        self.setIcon(icon(name, color or self._color, self._size, **kw))


class ToggleSwitch(QAbstractButton):
    """Interruptor animado (120 ms)."""

    def __init__(self, checked: bool = False):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(40, 22)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"pos_", self)
        self._anim.setDuration(120)
        self.toggled.connect(self._animate)

    def _get(self) -> float:
        return self._pos

    def _set(self, v: float) -> None:
        self._pos = v
        self.update()

    pos_ = Property(float, _get, _set)

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def set_checked_silent(self, on: bool) -> None:
        self.blockSignals(True)
        self.setChecked(on)
        self._pos = 1.0 if on else 0.0
        self.blockSignals(False)
        self.update()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        off, on = QColor(T.BORDER), QColor(T.ORANGE)
        t = self._pos
        col = QColor(int(off.red() + (on.red() - off.red()) * t), int(off.green() + (on.green() - off.green()) * t),
                     int(off.blue() + (on.blue() - off.blue()) * t))
        if not self.isEnabled():
            col.setAlpha(110)
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(0, 1, 40, 20), 10, 10)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(3 + 18 * t, 4, 14, 14))
        p.end()


class BannerLabel(QLabel):
    """Banner com recorte "cover" e cantos superiores arredondados."""

    def __init__(self, w: int, h: int, radius: int = T.RADIUS_LG, top_only: bool = True):
        super().__init__()
        self._w, self._h, self._radius, self._top_only = w, h, radius, top_only
        self.setFixedHeight(h)
        self.setMinimumWidth(w if w else 0)
        self._src = None
        self._seed, self._tint = "", T.BLUE

    def set_banner(self, path, seed: str, tint: str, width: int | None = None) -> None:
        self._src, self._seed, self._tint = path, seed, tint
        self._render(width or self._w)

    def _render(self, width: int) -> None:
        dpr = self.devicePixelRatioF() or 1.0
        pm = imagecache.cover_pixmap(self._src, width, self._h, dpr) if self._src else None
        if pm is None:
            pm = imagecache.placeholder_banner(self._seed, self._tint, width, self._h, dpr)
        self.setPixmap(imagecache.rounded(pm, self._radius, self._top_only))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if self._w == 0 and e.size().width() > 0 and (self.pixmap() is None or int(self.pixmap().width() / self.pixmap().devicePixelRatio()) != e.size().width()):
            self._render(e.size().width())


class StatBlock(QWidget):
    def __init__(self, icon_name: str, label: str):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(7)
        self.ic = QLabel()
        self.ic.setPixmap(pixmap(icon_name, T.TEXT_MUTED, 18))
        self.ic.setFixedSize(20, 20)
        lay.addWidget(self.ic, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.value = QLabel("—")
        self.value.setStyleSheet(f"font-size:{T.FS_LG}px; font-weight:700; background:transparent;")
        self.label = QLabel(label)
        self.label.setStyleSheet(f"font-size:{T.FS_XS}px; color:{T.TEXT_MUTED}; background:transparent;")
        col.addWidget(self.value)
        col.addWidget(self.label)
        lay.addLayout(col)

    def set(self, value: str, label: str | None = None) -> None:
        self.value.setText(value)
        if label is not None:
            self.label.setText(label)


# ---------- card ----------
class ProfileCard(QFrame):
    play = Signal(str)
    details = Signal(str)
    selected = Signal(str)
    menu_requested = Signal(str, QPoint)
    favorite_toggled = Signal(str)

    def __init__(self, p: Profile):
        super().__init__()
        self.pid = p.id
        self._selected = False
        self.setObjectName("pcard")
        self.setFixedSize(T.CARD_W, T.CARD_H)
        self.setCursor(Qt.PointingHandCursor)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(0)
        self._shadow.setOffset(0, 0)
        self._shadow.setColor(QColor(T.ORANGE))
        self.setGraphicsEffect(self._shadow)
        self._glow = QPropertyAnimation(self._shadow, b"blurRadius", self)
        self._glow.setDuration(T.ANIM_MS)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.banner = BannerLabel(T.CARD_W - 4, T.BANNER_H)
        lay.addWidget(self.banner)
        self.star = IconButton("star", "Favoritar", 17, T.TEXT, 30, flat=True)
        self.star.setParent(self.banner)
        self.star.setStyleSheet("QToolButton { background:rgba(16,19,24,170); border:none; border-radius:15px; }"
                                f"QToolButton:hover {{ background:{T.ORANGE_DIM}; }}")
        self.star.move(T.CARD_W - 4 - 38, 8)
        self.star.clicked.connect(lambda: self.favorite_toggled.emit(self.pid))

        body = QVBoxLayout()
        body.setContentsMargins(14, 11, 14, 12)
        body.setSpacing(5)
        self.title = QLabel()
        self.title.setStyleSheet(f"font-size:{T.FS_XL}px; font-weight:700; background:transparent;")
        self.sub = QLabel()
        self.sub.setStyleSheet(f"color:{T.TEXT_MUTED}; background:transparent;")
        self.mode = QLabel()
        self.mode.setStyleSheet(f"color:{T.TEXT_MUTED}; background:transparent;")
        body.addWidget(self.title)
        body.addWidget(self.sub)
        body.addWidget(self.mode)
        self.badges = QHBoxLayout()
        self.badges.setSpacing(6)
        body.addLayout(self.badges)
        body.addSpacing(2)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{T.BORDER_SOFT};")
        body.addWidget(line)
        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.s_time = StatBlock("clock", "Último jogo")
        self.s_saves = StatBlock("save", "Saves")
        self.s_mods = StatBlock("puzzle", "Mods")
        for s in (self.s_time, self.s_saves, self.s_mods):
            stats.addWidget(s, 1)
        body.addLayout(stats)
        body.addStretch()
        row = QHBoxLayout()
        row.setSpacing(8)
        self.play_btn = QPushButton("  JOGAR")
        self.play_btn.setObjectName("primary")
        self.play_btn.setIcon(icon("play", T.ORANGE_ON, 14))
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.setMinimumHeight(36)
        self.play_btn.clicked.connect(lambda: self.play.emit(self.pid))
        self.det_btn = QPushButton("Detalhes")
        self.det_btn.setMinimumHeight(36)
        self.det_btn.setCursor(Qt.PointingHandCursor)
        self.det_btn.clicked.connect(lambda: self.details.emit(self.pid))
        self.more = IconButton("more_v", "Mais ações", 16, T.TEXT, 36)
        self.more.clicked.connect(lambda: self.menu_requested.emit(self.pid, self.more.mapToGlobal(QPoint(0, self.more.height()))))
        row.addWidget(self.play_btn, 1)
        row.addWidget(self.det_btn)
        row.addWidget(self.more)
        body.addLayout(row)
        lay.addLayout(body, 1)
        self._style()

    # ---- estado visual ----
    def _style(self) -> None:
        border = T.ORANGE if self._selected else T.BORDER_SOFT
        self.setStyleSheet(f"QFrame#pcard {{ background:{T.CARD}; border:2px solid {border}; border-radius:{T.RADIUS_LG}px; }}"
                           f"QFrame#pcard:hover {{ border-color:{T.ORANGE if self._selected else '#4a566b'}; }}")

    def set_selected(self, sel: bool) -> None:
        if sel == self._selected:
            return
        self._selected = sel
        self._style()
        self._glow.stop()
        self._glow.setStartValue(self._shadow.blurRadius())
        self._glow.setEndValue(26 if sel else 0)
        self._glow.start()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self.selected.emit(self.pid)
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e) -> None:
        self.details.emit(self.pid)

    # ---- dados ----
    def update_profile(self, p: Profile, install, summary, banner_file, ready: bool, dlc_ok: bool = True) -> None:
        self.title.setText(p.name)
        self.title.setToolTip(p.name)
        fm = self.title.fontMetrics()
        self.title.setText(fm.elidedText(p.name, Qt.ElideRight, T.CARD_W - 40))
        self.star.set_icon("star", T.ORANGE if p.favorite else T.TEXT, filled=p.favorite, fill_color=T.ORANGE)
        self.star.setToolTip("Remover dos favoritos" if p.favorite else "Favoritar")
        self.banner.set_banner(banner_file, p.id, p.color, T.CARD_W - 4)
        n = summary.mods if summary else None
        if install is None:
            self.sub.setText(f"<span style='color:{T.RED}'>●</span> Instalação do Factorio ausente")
        elif not ready:
            self.sub.setText(f"<span style='color:{T.RED}'>●</span> Factorio {install.version} — executável não encontrado")
        else:
            self.sub.setText(f"<span style='color:{T.GREEN}'>●</span> Factorio {install.version}"
                             + (f"  •  {n} mods" if n is not None else ""))
        self.mode.setText("saves exclusivos" if p.save_mode == SAVE_EXCLUSIVE else "saves compartilhados")
        while self.badges.count():
            w = self.badges.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        if n is not None:
            self.badges.addWidget(Badge("Modpack" if n else "Vanilla", "gray", "puzzle" if n else "gear"))
        if install:
            self.badges.addWidget(Badge(install.version, "blue" if ready else "red", "gear"))
        self.badges.addWidget(Badge("Exclusivo" if p.save_mode == SAVE_EXCLUSIVE else "Compartilhado",
                                    "orange" if p.save_mode == SAVE_EXCLUSIVE else "blue",
                                    "save" if p.save_mode == SAVE_EXCLUSIVE else "cloud"))
        self.badges.addStretch()
        last = iso_to_ts(p.last_played) if p.last_played else None
        self.s_time.set(fmt_playtime(p.play_seconds), f"Último jogo\n{ago(last)}")
        self.s_saves.set("…" if summary is None else str(summary.saves), "Saves")
        self.s_mods.set("…" if summary is None else str(summary.mods), "Mods")
        self.play_btn.setEnabled(ready)
        self.play_btn.setToolTip("" if ready else "Instalação do Factorio indisponível — corrija em Configurações")
        self.det_btn.setToolTip("Gerenciar mods, saves, backups e configurações")
