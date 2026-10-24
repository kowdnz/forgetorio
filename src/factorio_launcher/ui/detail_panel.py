"""Painel lateral direito da Biblioteca: banner, ações, informações, mods e saves do perfil selecionado."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget)

from ..models.entities import SAVE_EXCLUSIVE, SAVE_SHARED, ModInfo, Profile
from ..services import dependency_resolver, local_mods, steam_cloud
from ..services.install_detector import installed_dlcs
from ..services.profile_manager import ProfileError
from . import imagecache, tokens as T
from .common import error, human_size, open_folder
from .icons import icon, pixmap
from .library_widgets import Badge, ElidedLabel, IconButton, ToggleSwitch, ago, fmt_playtime, iso_to_ts
from .workers import run_async

MAX_MODS, MAX_SAVES = 5, 4


class Hero(QWidget):
    """Banner do topo do painel com degradê, nome do perfil, favorito e botão de fechar."""
    closed = Signal()
    favorite = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedHeight(168)
        self._pm: QPixmap | None = None
        self._src, self._seed, self._tint = None, "", T.BLUE
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        top = QHBoxLayout()
        top.addStretch()
        self.close_btn = IconButton("close", "Fechar painel", 16, T.TEXT, 32)
        self.close_btn.setStyleSheet("QToolButton { background:rgba(16,19,24,190); border:1px solid #3a4558; border-radius:8px; }"
                                     f"QToolButton:hover {{ border-color:{T.ORANGE}; }}")
        self.close_btn.clicked.connect(self.closed.emit)
        top.addWidget(self.close_btn)
        lay.addLayout(top)
        lay.addStretch()
        row = QHBoxLayout()
        self.star = IconButton("star", "Favoritar", 20, T.TEXT, 36, flat=True)
        self.star.setStyleSheet("QToolButton { background:rgba(16,19,24,170); border:1px solid #3a4558; border-radius:8px; }"
                                f"QToolButton:hover {{ border-color:{T.ORANGE}; }}")
        self.star.clicked.connect(self.favorite.emit)
        self.name = QLabel()
        self.name.setStyleSheet("font-size:24px; font-weight:800; background:transparent;")
        row.addWidget(self.star)
        row.addWidget(self.name, 1)
        lay.addLayout(row)

    def set_banner(self, path, seed: str, tint: str) -> None:
        self._src, self._seed, self._tint = path, seed, tint
        self._pm = None
        self.update()

    def paintEvent(self, e) -> None:
        w, h = self.width(), self.height()
        dpr = self.devicePixelRatioF() or 1.0
        if self._pm is None or self._pm.size() != QSize(int(w * dpr), int(h * dpr)):
            pm = imagecache.cover_pixmap(self._src, w, h, dpr) if self._src else None
            self._pm = pm or imagecache.placeholder_banner(self._seed, self._tint, w, h, dpr)
        p = QPainter(self)
        p.drawPixmap(0, 0, self._pm)
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0.0, QColor(16, 19, 24, 90))
        g.setColorAt(0.45, QColor(16, 19, 24, 0))
        g.setColorAt(1.0, QColor(23, 27, 35, 245))
        p.fillRect(0, 0, w, h, g)
        p.end()


class _Row(QFrame):
    """Linha de informação: ícone, rótulo, valor e (opcional) seta clicável."""
    clicked = Signal()

    def __init__(self, icon_name: str, label: str, clickable: bool = False):
        super().__init__()
        self._clickable = clickable
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 7, 0, 7)
        lay.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(pixmap(icon_name, T.TEXT_MUTED, 18))
        ic.setFixedSize(20, 20)
        lab = QLabel(label)
        lab.setStyleSheet(f"color:{T.TEXT_MUTED};")
        lab.setFixedWidth(128)
        self.value = QLabel()
        self.value.setWordWrap(True)
        self.value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lay.addWidget(ic)
        lay.addWidget(lab)
        lay.addWidget(self.value, 1)
        if clickable:
            self.setCursor(Qt.PointingHandCursor)
            ch = QLabel()
            ch.setPixmap(pixmap("chevron", T.TEXT_MUTED, 14))
            lay.addWidget(ch)
        self.setStyleSheet("background:transparent;")

    def set_elided(self, text: str) -> None:
        """Troca o valor por um rótulo que abrevia o meio do caminho."""
        lay = self.layout()
        idx = lay.indexOf(self.value)
        lay.removeWidget(self.value)
        self.value.deleteLater()
        self.value = ElidedLabel(text)
        lay.insertWidget(idx, self.value, 1)

    def mousePressEvent(self, e) -> None:
        if self._clickable and e.button() == Qt.LeftButton:
            self.clicked.emit()


def _section(title: str, link: str | None = None):
    row = QHBoxLayout()
    t = QLabel(title)
    t.setStyleSheet(f"font-size:{T.FS_LG + 1}px; font-weight:700; background:transparent;")
    row.addWidget(t)
    row.addStretch()
    btn = None
    if link:
        btn = QPushButton(link)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(f"QPushButton {{ border:none; background:transparent; color:{T.BLUE}; padding:0; font-weight:600; }}"
                          f"QPushButton:hover {{ color:{T.ORANGE_HOVER}; background:transparent; }}")
        row.addWidget(btn)
    return row, btn


def _letter_icon(name: str, size: int = 34) -> QPixmap:
    from .explore_page import placeholder_pixmap
    return placeholder_pixmap(name, size)


class DetailPanel(QFrame):
    closed = Signal()
    changed = Signal()                 # perfil/mods mudaram: a Biblioteca deve atualizar cards
    open_details = Signal(str, int)    # (profile_id, aba)
    play = Signal(str)
    play_save = Signal(str, str)       # (profile_id, caminho do save)
    edit = Signal(str)
    clone = Signal(str)
    menu = Signal(str, QPoint)
    favorite = Signal(str)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.pid: str | None = None
        self._gen = 0
        self.setObjectName("dpanel")
        self.setStyleSheet(f"QFrame#dpanel {{ background:{T.SIDEBAR}; border-left:1px solid {T.BORDER_SOFT}; }}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.hero = Hero()
        self.hero.closed.connect(self.closed.emit)
        self.hero.favorite.connect(lambda: self.pid and self.favorite.emit(self.pid))
        outer.addWidget(self.hero)
        actions = QVBoxLayout()
        actions.setContentsMargins(14, 12, 14, 10)
        actions.setSpacing(8)
        self.play_btn = QPushButton("  JOGAR")
        self.play_btn.setObjectName("primary")
        self.play_btn.setIcon(icon("play", T.ORANGE_ON, 16))
        self.play_btn.setMinimumHeight(42)
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.setStyleSheet(f"QPushButton#primary {{ font-size:{T.FS_LG}px; }}")
        self.play_btn.clicked.connect(lambda: self.pid and self.play.emit(self.pid))
        actions.addWidget(self.play_btn)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_edit = QPushButton("Editar")
        self.btn_edit.setIcon(icon("pencil", T.TEXT, 15))
        self.btn_clone = QPushButton("Clonar")
        self.btn_clone.setIcon(icon("copy", T.TEXT, 15))
        self.btn_folder = QPushButton("Abrir pasta")
        self.btn_folder.setIcon(icon("folder", T.TEXT, 15))
        self.btn_more = IconButton("more", "Mais ações", 16, T.TEXT, 34)
        for b in (self.btn_edit, self.btn_clone, self.btn_folder):
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(34)
            row.addWidget(b)
        row.addWidget(self.btn_more)
        actions.addLayout(row)
        outer.addLayout(actions)
        self.btn_edit.clicked.connect(lambda: self.pid and self.edit.emit(self.pid))
        self.btn_clone.clicked.connect(lambda: self.pid and self.clone.emit(self.pid))
        self.btn_folder.clicked.connect(self._open_folder)
        self.btn_more.clicked.connect(lambda: self.pid and self.menu.emit(self.pid, self.btn_more.mapToGlobal(QPoint(0, self.btn_more.height()))))

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body.setObjectName("dbody")
        self.body.setStyleSheet("QWidget#dbody { background:transparent; }")
        self.scroll.setWidget(self.body)
        outer.addWidget(self.scroll, 1)
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(16, 6, 16, 18)
        self.body_lay.setSpacing(4)

    # ---------- dados ----------
    def profile(self) -> Profile | None:
        return self.ctx.pm.get_profile(self.pid) if self.pid else None

    def show_profile(self, p: Profile) -> None:
        self.pid = p.id
        self._gen += 1
        gen = self._gen
        pm = self.ctx.pm
        inst = pm.get_install(p.install_id)
        ready = bool(inst and Path(inst.exe).is_file())
        self.hero.name.setText(p.name)
        self.hero.star.set_icon("star", T.ORANGE if p.favorite else T.TEXT, filled=p.favorite, fill_color=T.ORANGE)
        self.hero.set_banner(pm.banner_file(p), p.id, p.color)
        self.play_btn.setEnabled(ready)
        self.play_btn.setToolTip("" if ready else "Instalação do Factorio indisponível")
        self._clear()
        mods = pm.scan_mods_cached(p)
        saves = pm.list_saves(p)
        self._build_info(p, inst, ready, len(mods), len(saves))
        self._build_mods(p, inst, mods)
        self._build_saves(p, saves)
        self.body_lay.addStretch()
        # previews e ícones carregam fora da thread de UI
        run_async(lambda: self._load_assets(p, mods, saves), lambda res: gen == self._gen and self._apply_assets(res),
                  lambda e: None)

    def _clear(self) -> None:
        while self.body_lay.count():
            it = self.body_lay.takeAt(0)
            w = it.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
            elif it.layout():
                self._clear_layout(it.layout())

    def _clear_layout(self, lay) -> None:
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().setParent(None)
                it.widget().deleteLater()
            elif it.layout():
                self._clear_layout(it.layout())

    # ---------- seções ----------
    def _build_info(self, p: Profile, inst, ready: bool, n_mods: int, n_saves: int) -> None:
        head, _ = _section("Informações")
        self.body_lay.addLayout(head)
        rows = [("gear", "Versão do Factorio", f"{inst.version}" if inst else f"<span style='color:{T.RED}'>instalação ausente</span>", False, None),
                ("library", "Instalação", (f"<span style='color:{T.GREEN}'>● Pronta</span>" if ready else
                                           f"<span style='color:{T.RED}'>● Indisponível</span>"), False, None),
                ("puzzle", "Mods instalados", f"{n_mods} mods", True, 0),
                ("save", "Saves", f"{n_saves} saves", True, 1),
                ("gamepad", "Modo de saves", "Exclusivos (só deste perfil)" if p.save_mode == SAVE_EXCLUSIVE
                 else "Compartilhados (pasta comum do Factorio)", False, None)]
        last = iso_to_ts(p.last_played) if p.last_played else None
        when = f"{ago(last)} ({time.strftime('%d/%m/%Y %H:%M', time.localtime(last))})" if last else "Nunca jogado por aqui"
        rows.append(("clock", "Último jogo", when, False, None))
        if p.play_seconds:
            rows.append(("clock", "Tempo jogado", f"{fmt_playtime(p.play_seconds)} <span style='color:{T.TEXT_MUTED}'>(medido pelo launcher)</span>", False, None))
        rows.append(("folder", "Diretório", "", False, None))
        for ic, label, value, clickable, tab in rows:
            r = _Row(ic, label, clickable)
            if label == "Diretório":
                path = str(self.ctx.pm.profile_root(p.id))
                r.set_elided(path)
            elif label == "Instalação" and inst:
                r.value.setText(value)
                r.value.setToolTip(inst.path)
            else:
                r.value.setText(value)
            if clickable:
                r.clicked.connect(lambda t=tab: self.open_details.emit(self.pid, t))
            self.body_lay.addWidget(r)
        self.body_lay.addSpacing(10)

    def _build_mods(self, p: Profile, inst, mods: list[ModInfo]) -> None:
        head, link = _section(f"Mods ({len(mods)})", "Ver todos" if mods else None)
        if link:
            link.clicked.connect(lambda: self.open_details.emit(self.pid, 0))
        self.body_lay.addLayout(head)
        self._mod_icons: dict[str, QLabel] = {}
        if not mods:
            lab = QLabel("Perfil Vanilla — nenhum mod instalado.\nUse “Detalhes” para instalar ZIPs ou o Mod Portal.")
            lab.setObjectName("muted")
            lab.setWordWrap(True)
            self.body_lay.addWidget(lab)
            self.body_lay.addSpacing(10)
            return
        dlcs = installed_dlcs(inst) if inst else []
        problems = dependency_resolver.check_profile(mods, inst.version, dlcs) if inst else []
        bad = {pr.split(":")[0].split(" ")[0] for pr in problems}
        for m in mods[:MAX_MODS]:
            self.body_lay.addWidget(self._mod_row(p, m, m.name in bad))
        if len(mods) > MAX_MODS:
            more = QLabel(f"+ {len(mods) - MAX_MODS} mods — veja todos em Detalhes")
            more.setObjectName("muted")
            self.body_lay.addWidget(more)
        self.body_lay.addSpacing(10)

    def _mod_row(self, p: Profile, m: ModInfo, has_problem: bool) -> QWidget:
        w = QFrame()
        w.setStyleSheet(f"QFrame {{ background:transparent; border-radius:8px; }} QFrame:hover {{ background:{T.SURFACE}; }}")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(10)
        ic = QLabel()
        ic.setFixedSize(34, 34)
        ic.setPixmap(_letter_icon(m.title or m.name))
        ic.setScaledContents(True)
        self._mod_icons[m.name] = ic
        lay.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(0)
        t = QLabel(m.title or m.name)
        t.setStyleSheet("font-weight:600; background:transparent;")
        t.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        t.setToolTip(f"{m.name} {m.version}" + ("\n📌 versão fixada" if m.pinned else ""))
        v = QLabel(f"v{m.version}" + ("  📌" if m.pinned else ""))
        v.setStyleSheet(f"color:{T.TEXT_MUTED}; font-size:{T.FS_SM}px; background:transparent;")
        col.addWidget(t)
        col.addWidget(v)
        lay.addLayout(col, 1)
        dot = QLabel("●")
        color = T.RED if has_problem else (T.GREEN if m.enabled else T.TEXT_DISABLED)
        dot.setStyleSheet(f"color:{color}; background:transparent;")
        dot.setToolTip("Problema de dependência — veja o Diagnóstico em Detalhes" if has_problem else
                       ("Habilitado" if m.enabled else "Desabilitado"))
        lay.addWidget(dot)
        sw = ToggleSwitch(m.enabled)
        sw.setToolTip("Habilitar/desabilitar (respeita dependências)")
        sw.toggled.connect(lambda on, name=m.name, s=sw: self._toggle_mod(name, on, s))
        lay.addWidget(sw)
        return w

    def _toggle_mod(self, name: str, on: bool, sw: ToggleSwitch) -> None:
        p = self.profile()
        if p is None:
            return
        if self.ctx.runner.is_profile_running(p.id):
            error(self, "Perfil em execução", "Feche o Factorio antes de alterar mods deste perfil.")
            sw.set_checked_silent(not on)
            return
        problems = self.ctx.pm.toggle_problems(p, name, on)
        if problems:
            error(self, "Não é possível alterar este mod", "\n".join(problems) +
                  "\n\nUse Detalhes → Mods para ajustar as dependências.")
            sw.set_checked_silent(not on)
            return
        try:
            local_mods.set_enabled(self.ctx.pm.mods_dir(p), name, on)
        except local_mods.ModError as e:
            error(self, "Mod", str(e))
            sw.set_checked_silent(not on)
            return
        self.changed.emit()

    def _build_saves(self, p: Profile, saves: list[Path]) -> None:
        cloud = steam_cloud.list_cloud_saves() if p.save_mode == SAVE_SHARED else []
        local_names = {s.name for s in saves}
        cloud_only = [c for c in cloud if c.name not in local_names]
        head, link = _section(f"Saves ({len(saves)})", "Ver todos" if saves or cloud_only else None)
        if link:
            link.clicked.connect(lambda: self.open_details.emit(self.pid, 1))
        self.body_lay.addLayout(head)
        self._save_icons: dict[str, QLabel] = {}
        if not saves and not cloud_only:
            lab = QLabel("Nenhum save encontrado" + (" nesta pasta exclusiva." if p.save_mode == SAVE_EXCLUSIVE else "."))
            lab.setObjectName("muted")
            self.body_lay.addWidget(lab)
            return
        cloud_map = {c.name: c for c in cloud}
        for s in saves[:MAX_SAVES]:
            self.body_lay.addWidget(self._save_row(p, s, s.name in cloud_map))
        room = MAX_SAVES - min(len(saves), MAX_SAVES)
        for c in cloud_only[:max(room, 0)]:
            self.body_lay.addWidget(self._cloud_row(c))
        if cloud_only:
            note = QLabel(f"☁ {len(cloud_only)} save(s) só na Steam Cloud (lista somente leitura; a Steam baixa ao sincronizar).")
            note.setObjectName("muted")
            note.setWordWrap(True)
            self.body_lay.addWidget(note)

    def _save_row(self, p: Profile, path: Path, in_cloud: bool) -> QWidget:
        w = QFrame()
        w.setStyleSheet(f"QFrame {{ background:transparent; border-radius:8px; }} QFrame:hover {{ background:{T.SURFACE}; }}")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(10)
        ic = QLabel()
        ic.setFixedSize(58, 40)
        ic.setPixmap(pixmap("save", T.TEXT_MUTED, 22))
        ic.setAlignment(Qt.AlignCenter)
        ic.setStyleSheet(f"background:{T.SURFACE}; border-radius:6px;")
        self._save_icons[str(path)] = ic
        lay.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(0)
        name = QLabel(path.stem)
        name.setStyleSheet("font-weight:600; background:transparent;")
        name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        name.setToolTip(str(path))
        try:
            st = path.stat()
            meta = f"{ago(st.st_mtime)} • {human_size(st.st_size)}"
        except OSError:
            meta = "—"
        where = "☁ Steam Cloud + local" if in_cloud else ("local (perfil)" if p.save_mode == SAVE_EXCLUSIVE else "local")
        sub = QLabel(f"{meta} • {where}")
        sub.setStyleSheet(f"color:{T.TEXT_MUTED}; font-size:{T.FS_SM}px; background:transparent;")
        col.addWidget(name)
        col.addWidget(sub)
        lay.addLayout(col, 1)
        play = IconButton("play", "Carregar este save no jogo", 14, T.TEXT, 32)
        play.clicked.connect(lambda: self.pid and self.play_save.emit(self.pid, str(path)))
        lay.addWidget(play)
        return w

    def _cloud_row(self, c) -> QWidget:
        w = QFrame()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(pixmap("cloud", T.BLUE, 22))
        ic.setFixedSize(58, 40)
        ic.setAlignment(Qt.AlignCenter)
        ic.setStyleSheet(f"background:{T.BLUE_BG}; border-radius:6px;")
        lay.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(0)
        n = QLabel(Path(c.name).stem)
        n.setStyleSheet("font-weight:600; background:transparent;")
        n.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        s = QLabel(f"{ago(c.mtime)} • {human_size(c.size)} • ☁ só na nuvem")
        s.setStyleSheet(f"color:{T.TEXT_MUTED}; font-size:{T.FS_SM}px; background:transparent;")
        col.addWidget(n)
        col.addWidget(s)
        lay.addLayout(col, 1)
        return w

    # ---------- assets assíncronos ----------
    def _load_assets(self, p: Profile, mods: list[ModInfo], saves: list[Path]):
        icons = {m.name: self.ctx.pm.mod_icon(p, m) for m in mods[:MAX_MODS]}
        prevs = {str(s): self.ctx.pm.save_preview(s) for s in saves[:MAX_SAVES]}
        return icons, prevs

    def _apply_assets(self, res) -> None:
        icons, prevs = res
        dpr = self.devicePixelRatioF() or 1.0
        for name, path in icons.items():
            lab = self._mod_icons.get(name)
            if lab and path:
                pm = imagecache.cover_pixmap(path, 34, 34, dpr)
                if pm:
                    lab.setPixmap(imagecache.rounded(pm, 7))
        for key, path in prevs.items():
            lab = self._save_icons.get(key)
            if lab and path:
                pm = imagecache.cover_pixmap(path, 58, 40, dpr)
                if pm:
                    lab.setPixmap(imagecache.rounded(pm, 6))

    def _open_folder(self) -> None:
        p = self.profile()
        if p:
            open_folder(self.ctx.pm.profile_root(p.id))
