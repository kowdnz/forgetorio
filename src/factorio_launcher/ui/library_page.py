"""Biblioteca: filtros, busca, ordenação, grade de cards e painel lateral de detalhes."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect, Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ..models.entities import SAVE_EXCLUSIVE, Profile
from ..services.profile_manager import ProfileError, ProfileSummary
from . import tokens as T
from .common import error, info, open_folder
from .detail_panel import DetailPanel
from .dialogs import NewProfileDialog
from .icons import icon, pixmap
from .launching import launch_profile  # noqa: F401  (reexportado: usado por profile_page)
from .library_widgets import ProfileCard, iso_to_ts
from .profile_actions import EditProfileDialog, delete_profile, duplicate_profile
from .banner_dialog import BannerDialog
from .workers import run_async

FILTERS = [("all", "Todos", "library"), ("fav", "Favoritos", "star"), ("mods", "Com mods", "puzzle"),
           ("vanilla", "Vanilla", "gear")]
NARROW_BAR = 930   # largura útil mínima para chips + busca + ordenação na mesma linha
SORTS = [("played", "Último jogado"), ("name_az", "Nome A–Z"), ("name_za", "Nome Z–A"), ("created", "Data de criação"),
         ("mods", "Quantidade de mods")]
SYNC_LIMIT = 40   # até aqui os números dos cards são calculados na hora; acima disso, em segundo plano


class FilterChip(QPushButton):
    def __init__(self, key: str, label: str, icon_name: str):
        super().__init__()
        self.key, self.label, self.icon_name = key, label, icon_name
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(38)
        self.set_count(0)
        self.toggled.connect(lambda _: self._style())
        self._style()

    def set_count(self, n: int) -> None:
        self.setText(f"  {self.label} ({n})")
        f = self.font()
        f.setBold(True)   # largura calculada com o pior caso (negrito) + ícone + paddings do estilo
        from PySide6.QtGui import QFontMetrics
        self.setFixedWidth(QFontMetrics(f).horizontalAdvance(self.text()) + 16 + 20 + 16)

    def _style(self) -> None:
        on = self.isChecked()
        self.setIcon(icon(self.icon_name, T.ORANGE if on else T.TEXT_MUTED, 16))
        self.setStyleSheet(
            f"QPushButton {{ background:{T.ORANGE_DIM if on else T.CARD}; border:1px solid {T.ORANGE if on else T.BORDER_SOFT};"
            f" border-radius:10px; padding:4px 10px; color:{T.TEXT if on else T.TEXT_MUTED}; font-weight:{600 if on else 500}; }}"
            f"QPushButton:hover {{ border-color:{T.ORANGE}; color:{T.TEXT}; }}")


class LibraryPage(QWidget):
    def __init__(self, ctx, win):
        super().__init__()
        self.ctx, self.win = ctx, win
        self._profiles: list[Profile] = []
        self._summaries: dict[str, ProfileSummary] = {}
        self._cards: dict[str, ProfileCard] = {}
        self._selected: str | None = None
        self._filter = ctx.settings().get("library_filter", "all")
        self._sort = ctx.settings().get("library_sort", "played")
        self._panel_open = False
        self._gen = 0
        self._columns = 0

        # ---- coluna de conteúdo ----
        self.content = QWidget(self)
        cl = QVBoxLayout(self.content)
        cl.setContentsMargins(34, 28, 34, 0)
        cl.setSpacing(16)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        t = QLabel("Biblioteca")
        t.setStyleSheet(f"font-size:{T.FS_H1}px; font-weight:800;")
        s = QLabel("Gerencie seus perfis de Factorio e modpacks.")
        s.setStyleSheet(f"color:{T.TEXT_MUTED}; font-size:{T.FS_LG - 1}px;")
        titles.addWidget(t)
        titles.addWidget(s)
        head.addLayout(titles)
        head.addStretch()
        self.new_btn = QPushButton("  Novo perfil")
        self.new_btn.setObjectName("primary")
        self.new_btn.setIcon(icon("plus", T.ORANGE_ON, 16))
        self.new_btn.setMinimumHeight(42)
        self.new_btn.setCursor(Qt.PointingHandCursor)
        self.new_btn.setStyleSheet(f"QPushButton#primary {{ padding:8px 20px; font-size:{T.FS_LG - 1}px; }}")
        self.new_btn.clicked.connect(self.new_profile)
        head.addWidget(self.new_btn, 0, Qt.AlignTop)
        cl.addLayout(head)

        self.bar = QVBoxLayout()
        self.bar.setSpacing(10)
        chips_row = QHBoxLayout()
        chips_row.setSpacing(8)
        self.chips: dict[str, FilterChip] = {}
        for key, label, ic in FILTERS:
            c = FilterChip(key, label, ic)
            c.clicked.connect(lambda _=False, k=key: self.set_filter(k))
            self.chips[key] = c
            chips_row.addWidget(c)
        chips_row.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar perfis…")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(40)
        self.search.setMinimumWidth(180)
        self.search.setMaximumWidth(340)
        self.search.addAction(icon("search", T.TEXT_MUTED, 16), QLineEdit.LeadingPosition)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(160)
        self._search_timer.timeout.connect(self._apply_view)
        self.search.textChanged.connect(lambda _: self._search_timer.start())
        self.sort = QComboBox()
        self.sort.setMinimumHeight(40)
        for key, label in SORTS:
            self.sort.addItem(f"Ordenar: {label}", key)
        self.sort.setCurrentIndex(max(0, self.sort.findData(self._sort)))
        self.sort.currentIndexChanged.connect(self._sort_changed)
        self.sort.setMinimumWidth(190)
        self._row_a = chips_row                 # chips (+ busca e ordenação quando há espaço)
        self._row_b = QHBoxLayout()             # busca e ordenação quando a largura é curta
        self._row_b.setSpacing(10)
        self.bar.addLayout(self._row_a)
        self.bar.addLayout(self._row_b)
        self._bar_narrow = None
        self._layout_bar()
        cl.addLayout(self.bar)

        self.banner = QFrame()
        self.banner.setObjectName("banner")
        bl = QHBoxLayout(self.banner)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        bl.addWidget(self.banner_text, 1)
        self.banner_btn = QPushButton("Detectar Factorio")
        self.banner_btn.clicked.connect(lambda: win.goto(win.settings))
        bl.addWidget(self.banner_btn)
        cl.addWidget(self.banner)

        self.empty = QFrame()
        self.empty.setObjectName("card")
        el = QVBoxLayout(self.empty)
        el.setContentsMargins(30, 40, 30, 40)
        el.setAlignment(Qt.AlignCenter)
        self.empty_icon = QLabel()
        self.empty_icon.setAlignment(Qt.AlignCenter)
        self.empty_title = QLabel()
        self.empty_title.setAlignment(Qt.AlignCenter)
        self.empty_title.setStyleSheet(f"font-size:{T.FS_XL}px; font-weight:700; background:transparent;")
        self.empty_text = QLabel()
        self.empty_text.setAlignment(Qt.AlignCenter)
        self.empty_text.setWordWrap(True)
        self.empty_text.setStyleSheet(f"color:{T.TEXT_MUTED}; background:transparent;")
        self.empty_btn = QPushButton("Criar primeiro perfil")
        self.empty_btn.setObjectName("primary")
        self.empty_btn.clicked.connect(self.new_profile)
        for w in (self.empty_icon, self.empty_title, self.empty_text):
            el.addWidget(w)
        el.addWidget(self.empty_btn, 0, Qt.AlignCenter)
        cl.addWidget(self.empty)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.holder = QWidget()
        self.holder.setObjectName("libholder")
        self.holder.setStyleSheet("QWidget#libholder { background:transparent; }")
        self.grid = QGridLayout(self.holder)
        self.grid.setContentsMargins(0, 4, 0, 24)
        self.grid.setSpacing(T.CARD_GAP)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll.setWidget(self.holder)
        cl.addWidget(self.scroll, 1)

        # ---- painel de detalhes (posicionado manualmente: docado ou gaveta) ----
        self.panel = DetailPanel(ctx)
        self.panel.setParent(self)
        self.panel.hide()
        self.panel.closed.connect(self.close_panel)
        self.panel.changed.connect(self._on_panel_changed)
        self.panel.open_details.connect(lambda pid, tab: self._open_profile_page(pid, tab))
        self.panel.play.connect(self._play)
        self.panel.play_save.connect(self._play_save)
        self.panel.edit.connect(self._edit)
        self.panel.clone.connect(self._clone)
        self.panel.menu.connect(self._card_menu)
        self.panel.favorite.connect(self._toggle_favorite)
        self._slide = QPropertyAnimation(self.panel, b"geometry", self)
        self._slide.setDuration(T.ANIM_MS)
        self._slide.setEasingCurve(QEasingCurve.OutCubic)
        self._slide.finished.connect(self._after_slide)
        self._restoring = ctx.settings().get("library_selected")

    # ---------- layout ----------
    @property
    def docked(self) -> bool:
        return self.width() >= T.PANEL_DOCK_MIN_W

    def _panel_width(self) -> int:
        return min(T.PANEL_W, max(320, self.width() - 80)) if not self.docked else T.PANEL_W

    def _panel_rect(self) -> QRect:
        w = self._panel_width()
        return QRect(self.width() - w, 0, w, self.height())

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._relayout()

    def _layout_bar(self) -> None:
        narrow = (self.content.width() - 68) < NARROW_BAR
        if narrow == self._bar_narrow:
            return
        self._bar_narrow = narrow
        for lay in (self._row_a, self._row_b):
            for w in (self.search, self.sort):
                lay.removeWidget(w)
        if narrow:
            self._row_b.addWidget(self.search, 1)
            self._row_b.addWidget(self.sort)
            self.search.setMaximumWidth(16777215)
        else:
            self._row_a.addWidget(self.search, 1)
            self._row_a.addWidget(self.sort)
            self.search.setMaximumWidth(340)

    def _relayout(self) -> None:
        pw = self._panel_width() if self._panel_open and self.docked else 0
        self.content.setGeometry(0, 0, self.width() - pw, self.height())
        self._layout_bar()
        if self._panel_open:
            self._slide.stop()
            self.panel.setGeometry(self._panel_rect())
            self.panel.raise_()
        self._reflow()

    def _reflow(self) -> None:
        avail = self.scroll.viewport().width()
        cols = max(1, (avail + T.CARD_GAP) // (T.CARD_W + T.CARD_GAP))
        if cols == self._columns and self.grid.count() == len(self._visible_ids()):
            return
        self._columns = cols
        self._place_cards()

    def _after_slide(self) -> None:
        if not self._panel_open:
            self.panel.hide()

    # ---------- dados ----------
    def refresh(self) -> None:
        pm = self.ctx.pm
        self._profiles = pm.list_profiles()
        ids = {p.id for p in self._profiles}
        installs = pm.list_installs()
        self.banner.setVisible(not installs)
        if not installs:
            self.banner_text.setText("Nenhuma instalação do Factorio cadastrada. Detecte ou selecione o jogo em "
                                     "Configurações para criar perfis e jogar.")
        for pid in [k for k in self._cards if k not in ids]:
            c = self._cards.pop(pid)
            c.setParent(None)
            c.deleteLater()
            self._summaries.pop(pid, None)
        for p in self._profiles:
            if p.id not in self._cards:
                c = ProfileCard(p)
                c.selected.connect(self.select)
                c.play.connect(self._play)
                c.details.connect(lambda pid: self._open_profile_page(pid, 0))
                c.menu_requested.connect(self._card_menu)
                c.favorite_toggled.connect(self._toggle_favorite)
                self._cards[p.id] = c
        self._gen += 1
        if len(self._profiles) <= SYNC_LIMIT:
            self._summaries = {p.id: pm.summary(p) for p in self._profiles}
            self._after_summaries()
        else:
            for p in self._profiles:
                self._update_card(p)
            gen, profs = self._gen, list(self._profiles)
            run_async(lambda: {p.id: pm.summary(p) for p in profs},
                      lambda res: (gen == self._gen) and (self._summaries.update(res), self._after_summaries()),
                      lambda e: None)
            self._apply_view()
        if self._restoring:
            rid, self._restoring = self._restoring, None
            if rid in ids:
                self._select(rid, animate=False)
        elif self._selected and self._selected not in ids:
            self.close_panel(animate=False)
        elif self._selected and self._panel_open:
            self._show_in_panel()

    def _after_summaries(self) -> None:
        for p in self._profiles:
            self._update_card(p)
        self._apply_view()

    def _update_card(self, p: Profile) -> None:
        pm = self.ctx.pm
        inst = pm.get_install(p.install_id)
        ready = bool(inst and Path(inst.exe).is_file())
        self._cards[p.id].update_profile(p, inst, self._summaries.get(p.id), pm.banner_file(p, thumb=True), ready)
        self._cards[p.id].set_selected(p.id == self._selected)

    # ---------- filtros / busca / ordenação ----------
    def set_filter(self, key: str) -> None:
        self._filter = key
        self.ctx.set_setting("library_filter", key)
        self._apply_view()

    def _sort_changed(self) -> None:
        self._sort = self.sort.currentData()
        self.ctx.set_setting("library_sort", self._sort)
        self._apply_view()

    def _matches_filter(self, p: Profile, key: str) -> bool:
        s = self._summaries.get(p.id)
        if key == "all":
            return True
        if key == "fav":
            return p.favorite
        if key == "excl":
            return p.save_mode == SAVE_EXCLUSIVE
        if key == "shared":
            return p.save_mode != SAVE_EXCLUSIVE
        if s is None:
            return False
        return s.mods > 0 if key == "mods" else s.mods == 0

    def _matches_query(self, p: Profile, q: str) -> bool:
        if not q:
            return True
        inst = self.ctx.pm.get_install(p.install_id)
        mode = "exclusivo exclusivos" if p.save_mode == SAVE_EXCLUSIVE else "compartilhado compartilhados"
        hay = [p.name, p.notes, mode, inst.version if inst else ""]
        cached = self.ctx.pm._mods_cache.get(p.id)
        if cached:
            hay += [f"{m.name} {m.title}" for m in cached[1]]
        text = " ".join(hay).lower()
        return all(t in text for t in q.lower().split())

    def _sorted(self, profs: list[Profile]) -> list[Profile]:
        key = self._sort
        if key == "name_az":
            return sorted(profs, key=lambda p: p.name.lower())
        if key == "name_za":
            return sorted(profs, key=lambda p: p.name.lower(), reverse=True)
        if key == "created":
            return sorted(profs, key=lambda p: p.created_at, reverse=True)
        if key == "mods":
            return sorted(profs, key=lambda p: (-(self._summaries[p.id].mods if p.id in self._summaries else 0), p.name.lower()))
        # último jogado: quem nunca jogou vai para o fim, em ordem de criação
        return sorted(profs, key=lambda p: (iso_to_ts(p.last_played) or 0, p.created_at), reverse=True)

    def _visible_profiles(self) -> list[Profile]:
        q = self.search.text().strip()
        return self._sorted([p for p in self._profiles if self._matches_filter(p, self._filter) and self._matches_query(p, q)])

    def _visible_ids(self) -> list[str]:
        return [p.id for p in self._visible_profiles()]

    def _apply_view(self) -> None:
        for key, chip in self.chips.items():
            chip.set_count(sum(1 for p in self._profiles if self._matches_filter(p, key)))
            chip.blockSignals(True)
            chip.setChecked(key == self._filter)
            chip.blockSignals(False)
            chip._style()
        vis = self._visible_profiles()
        total = len(self._profiles)
        self.empty.setVisible(not vis)
        self.scroll.setVisible(bool(vis))
        if not vis:
            if total == 0:
                self.empty_icon.setPixmap(pixmap("library", T.TEXT_MUTED, 44))
                self.empty_title.setText("Nenhum perfil ainda")
                self.empty_text.setText("Crie um perfil para ter mods e saves independentes para cada modpack.")
                self.empty_btn.show()
            else:
                self.empty_icon.setPixmap(pixmap("search", T.TEXT_MUTED, 44))
                self.empty_title.setText("Nenhum resultado")
                self.empty_text.setText("Nenhum perfil corresponde à busca ou ao filtro selecionado.")
                self.empty_btn.hide()
        self._columns = 0
        self._place_cards()

    def _place_cards(self) -> None:
        vis = self._visible_profiles()
        shown = {p.id for p in vis}
        while self.grid.count():
            self.grid.takeAt(0)
        for pid, c in self._cards.items():
            if pid not in shown:
                c.hide()
        cols = max(1, (self.scroll.viewport().width() + T.CARD_GAP) // (T.CARD_W + T.CARD_GAP))
        self._columns = cols
        for i, p in enumerate(vis):
            c = self._cards[p.id]
            self.grid.addWidget(c, i // cols, i % cols, Qt.AlignTop | Qt.AlignLeft)
            c.setParent(self.holder)
            c.show()

    # ---------- seleção / painel ----------
    def select(self, pid: str) -> None:
        self._select(pid, animate=True)

    def _select(self, pid: str, animate: bool) -> None:
        if self._selected and self._selected in self._cards:
            self._cards[self._selected].set_selected(False)
        self._selected = pid
        if pid in self._cards:
            self._cards[pid].set_selected(True)
        self.ctx.set_setting("library_selected", pid)
        self._show_in_panel(animate)

    def _show_in_panel(self, animate: bool = False) -> None:
        p = self.ctx.pm.get_profile(self._selected) if self._selected else None
        if p is None:
            self.close_panel(animate=False)
            return
        self.panel.show_profile(p)
        if not self._panel_open:
            self._panel_open = True
            target = self._panel_rect()
            self.panel.show()
            self.panel.raise_()
            self.content.setGeometry(0, 0, self.width() - (target.width() if self.docked else 0), self.height())
            self._reflow()
            if animate:
                self._slide.stop()
                self._slide.setStartValue(QRect(self.width(), 0, target.width(), self.height()))
                self._slide.setEndValue(target)
                self._slide.start()
            else:
                self.panel.setGeometry(target)

    def close_panel(self, animate: bool = True) -> None:
        if self._selected and self._selected in self._cards:
            self._cards[self._selected].set_selected(False)
        self._selected = None
        self.ctx.set_setting("library_selected", None)
        if not self._panel_open:
            return
        self._panel_open = False
        if animate and self.isVisible():
            self._slide.stop()
            self._slide.setStartValue(self.panel.geometry())
            self._slide.setEndValue(QRect(self.width(), 0, self.panel.width(), self.height()))
            self._slide.start()
        else:
            self.panel.hide()
        self.content.setGeometry(0, 0, self.width(), self.height())
        self._reflow()

    def _on_panel_changed(self) -> None:
        """Um mod foi (des)habilitado no painel: atualiza números/estado dos cards sem reconstruir a página."""
        self.refresh()

    def on_game_exit(self, pid: str, seconds: int) -> None:
        from .launching import MIN_SESSION_SECONDS
        if seconds >= MIN_SESSION_SECONDS:
            self.ctx.pm.add_play_time(pid, seconds)
        if self.isVisible():
            self.refresh()

    # ---------- ações ----------
    def _profile(self, pid: str) -> Profile | None:
        return self.ctx.pm.get_profile(pid)

    def _play(self, pid: str) -> None:
        p = self._profile(pid)
        if p and launch_profile(self.ctx, self, p):
            self.refresh()

    def _play_save(self, pid: str, path: str) -> None:
        p = self._profile(pid)
        if p and launch_profile(self.ctx, self, p, ["--load-game", path]):
            self.refresh()

    def _open_profile_page(self, pid: str, tab: int = 0) -> None:
        self.win.open_profile(pid)
        self.win.profile_page.tabs.setCurrentIndex(tab)

    def _toggle_favorite(self, pid: str) -> None:
        p = self._profile(pid)
        if p:
            self.ctx.pm.set_favorite(p, not p.favorite)
            self.refresh()

    def _edit(self, pid: str) -> None:
        p = self._profile(pid)
        if p and EditProfileDialog(self.ctx, self, p).exec():
            self.refresh()
        elif p:
            self.refresh()

    def _clone(self, pid: str) -> None:
        p = self._profile(pid)
        q = duplicate_profile(self.ctx, self, p) if p else None
        if q:
            self.refresh()
            self.select(q.id)

    def _delete(self, pid: str) -> None:
        p = self._profile(pid)
        if p and delete_profile(self.ctx, self, p):
            if self._selected == pid:
                self.close_panel(animate=False)
            self.refresh()

    def _card_menu(self, pid: str, pos) -> None:
        p = self._profile(pid)
        if not p:
            return
        m = QMenu(self)
        inst = self.ctx.pm.get_install(p.install_id)
        a_play = m.addAction(icon("play", T.TEXT, 15), "Jogar")
        a_play.setEnabled(bool(inst and Path(inst.exe).is_file()))
        a_det = m.addAction(icon("gear", T.TEXT, 15), "Detalhes e gerenciamento")
        m.addSeparator()
        a_edit = m.addAction(icon("pencil", T.TEXT, 15), "Editar nome e cor…")
        a_ban = m.addAction(icon("image", T.TEXT, 15), "Alterar banner…")
        a_fav = m.addAction(icon("star", T.TEXT, 15), "Remover dos favoritos" if p.favorite else "Adicionar aos favoritos")
        a_clone = m.addAction(icon("copy", T.TEXT, 15), "Clonar")
        a_dir = m.addAction(icon("folder", T.TEXT, 15), "Abrir pasta do perfil")
        m.addSeparator()
        a_del = m.addAction(icon("trash", T.RED, 15), "Excluir…")
        act = m.exec(pos)
        if act is a_play:
            self._play(pid)
        elif act is a_det:
            self._open_profile_page(pid, 0)
        elif act is a_edit:
            self._edit(pid)
        elif act is a_ban:
            BannerDialog(self.ctx, self, p).exec()
            self.refresh()
        elif act is a_fav:
            self._toggle_favorite(pid)
        elif act is a_clone:
            self._clone(pid)
        elif act is a_dir:
            open_folder(self.ctx.pm.profile_root(pid))
        elif act is a_del:
            self._delete(pid)

    def new_profile(self) -> None:
        installs = self.ctx.pm.list_installs()
        if not installs:
            error(self, "Novo perfil", "Cadastre uma instalação do Factorio em Configurações primeiro.")
            self.win.goto(self.win.settings)
            return
        dlg = NewProfileDialog(self, installs, self.ctx.pm.list_profiles())
        if not dlg.exec():
            return
        v = dlg.values()
        inst = self.ctx.pm.get_install(v["install_id"])
        try:
            if v["template"] == "duplicate":
                src = self.ctx.pm.get_profile(v["source_id"])
                p = self.ctx.pm.create_profile(v["name"], inst, v["save_mode"], "duplicate", src, v["color"],
                                               copy_saves=v["copy_saves"])
            else:
                p = self.ctx.pm.create_profile(v["name"], inst, v["save_mode"], "empty", color=v["color"])
                if v["template"] == "import_current":
                    done, skipped = self.ctx.pm.import_system_mods(p)
                    info(self, "Importação", f"{len(done)} mods copiados (a pasta original não foi alterada)."
                         + ("\n\nIgnorados:\n" + "\n".join(skipped[:15]) if skipped else ""))
        except (ProfileError, OSError) as e:
            error(self, "Novo perfil", str(e))
            return
        self.refresh()
        self.select(p.id)
