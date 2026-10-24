"""Explorar Mods — layout inspirado no navegador de mods do próprio Factorio:
filtros à esquerda (categorias, tags, compatibilidade), lista com ícones no centro, detalhes à direita.

Busca:
  • Com credenciais do Portal → POST /api/search (tags, exclusão de tags, categorias, ordenação e relevância do servidor).
  • Sem credenciais/offline → catálogo local em cache (sem tags: a API de busca exige usuário + token).
Comandos no buscador: `$trains`, `$trains $logistics` (todas as tags), `-$combat` (excluir), `cargo $trains`.
"""
from __future__ import annotations

import html
import time
from datetime import datetime, timezone

from PySide6.QtCore import QEvent, QObject, QPoint, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from ..models.versions import parse_dependencies, parse_version
from ..services import dependency_resolver, tags as taglib
from ..services.install_detector import installed_dlcs
from ..services.portal_client import AuthRequired, PortalError, PortalOffline, Release, game_compat
from .common import error
from .dialogs import TextReportDialog
from .workers import run_async

PAGE = 20
ORANGE, ORANGE_TXT, PANEL, INNER, LINE = "#e39827", "#ffe6c0", "#313131", "#242323", "#454545"

CATEGORIES = [("content", "Conteúdo"), ("overhaul", "Reimaginado"), ("tweaks", "Alterações pequenas"),
              ("utilities", "Utilidades"), ("scenarios", "Cenários"), ("mod-packs", "Modpacks"),
              ("localizations", "Localização"), ("internal", "Interno"), ("no-category", "Sem categoria")]
CAT_NAME = dict(CATEGORIES)

QSS = f"""
#fpanel {{ background:{PANEL}; border:2px solid #1b1b1b; border-radius:2px; }}
#finner {{ background:{INNER}; border:1px solid #1b1b1b; }}
#fhead {{ color:{ORANGE_TXT}; font-weight:700; font-size:14px; }}
#fmuted {{ color:#a8a8a8; }}
QCheckBox {{ spacing:8px; }}
QCheckBox::indicator {{ width:14px; height:14px; border:1px solid #6b6b6b; background:#1d1d1d; }}
QCheckBox::indicator:checked {{ background:{ORANGE}; border-color:{ORANGE}; }}
QToolButton#fexcl {{ border:1px solid #1b1b1b; background:#3a3a3a; color:#9a9a9a; padding:0 4px; }}
QToolButton#fexcl:checked {{ background:#a33; color:#fff; }}
QListWidget#flist {{ background:{INNER}; border:1px solid #1b1b1b; outline:0; }}
QListWidget#flist::item {{ border-bottom:1px solid #1b1b1b; }}
QListWidget#flist::item:selected {{ background:{ORANGE}; }}
QListWidget#flist::item:hover:!selected {{ background:#3a3a3a; }}
QListWidget#tagpopup {{ background:#202020; border:1px solid {ORANGE}; outline:0; }}
QListWidget#tagpopup::item {{ padding:4px 8px; }}
QListWidget#tagpopup::item:selected {{ background:{ORANGE}; color:#1a1205; }}
QPushButton#fpage {{ min-width:28px; padding:4px 6px; background:#4a4a4a; border:1px solid #1b1b1b; }}
QPushButton#fpage:checked {{ background:{ORANGE}; color:#1a1205; font-weight:700; }}
QPushButton#fgreen {{ background:#5e9c3a; color:#fff; font-weight:700; border:1px solid #1b1b1b; }}
QPushButton#fgreen:disabled {{ background:#3f4a38; color:#8b8b8b; }}
"""


def category_label(c: str) -> str:
    return CAT_NAME.get(c, c)


def ago(iso: str) -> str:
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
    except ValueError:
        return "—"
    s = (datetime.now(timezone.utc) - t).total_seconds()
    for lim, div, unit in ((3600, 60, "min"), (86400, 3600, "h"), (86400 * 30, 86400, "dia(s)"),
                           (86400 * 365, 86400 * 30, "mês(es)"), (1e12, 86400 * 365, "ano(s)")):
        if s < lim:
            return f"há {max(int(s // div), 1)} {unit}"
    return "—"


def placeholder_pixmap(name: str, size: int = 64) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(QColor.fromHsv(sum(map(ord, name)) % 360, 90, 70))
    p = QPainter(pm)
    p.setPen(QColor("#ffffffcc"))
    p.setFont(QFont("Segoe UI", size // 3, QFont.Bold))
    p.drawText(pm.rect(), Qt.AlignCenter, (name[:1] or "?").upper())
    p.end()
    return pm


class _ThumbSignals(QObject):
    ready = Signal(str, str)


class _ThumbJob(QRunnable):
    """Baixa miniaturas da página visível, uma a uma (respeita o limitador do cliente)."""

    def __init__(self, portal, items: list[tuple[str, str]], token: list, my_token: int, signals: _ThumbSignals):
        super().__init__()
        self.portal, self.items, self.token, self.my, self.signals = portal, items, token, my_token, signals

    def run(self) -> None:
        for name, rel in self.items:
            if self.token[0] != self.my:
                return
            path = self.portal.thumbnail(name, rel or None)
            if path:
                try:
                    self.signals.ready.emit(name, str(path))
                except RuntimeError:   # página destruída (app encerrando)
                    return


class ModRow(QWidget):
    def __init__(self, m: dict, installed_version: str | None):
        super().__init__()
        self.name = m["name"]
        self.setFixedHeight(104)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 8, 6)
        self.icon = QLabel()
        self.icon.setFixedSize(64, 64)
        self.icon.setPixmap(placeholder_pixmap(m["title"] or m["name"]))
        self.icon.setScaledContents(True)
        lay.addWidget(self.icon, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        top = QHBoxLayout()
        self.title = QLabel(m["title"] or m["name"])
        self.title.setStyleSheet(f"font-weight:700; color:{ORANGE_TXT}; background:transparent;")
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.ver = QLabel(m["version"])
        self.ver.setStyleSheet("background:transparent;")
        top.addWidget(self.title, 1)
        top.addWidget(self.ver)
        col.addLayout(top)
        self.author = QLabel(m["owner"])
        self.author.setStyleSheet(f"font-weight:700; color:{ORANGE}; background:transparent;")
        col.addWidget(self.author)
        summ = (m["summary"] or "").replace("\n", " ")
        self.summary = QLabel(summ[:170] + ("…" if len(summ) > 170 else ""))
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("background:transparent;")
        self.summary.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        col.addWidget(self.summary, 1)
        foot = f"{category_label(m['category'])}     {ago(m.get('at', ''))}     ⬇ {m['downloads']:,}".replace(",", ".")
        if installed_version:
            foot += f"     ✔ instalado {installed_version}"
        self.foot = QLabel(foot)
        self.foot.setStyleSheet("color:#bdbdbd; background:transparent;")
        col.addWidget(self.foot)
        lay.addLayout(col, 1)

    def set_pixmap(self, path: str) -> None:
        pm = QPixmap(path)
        if not pm.isNull():
            self.icon.setPixmap(pm)

    def set_selected(self, sel: bool) -> None:
        dark = "#1a1205"
        self.title.setStyleSheet(f"font-weight:700; color:{dark if sel else ORANGE_TXT}; background:transparent;")
        self.author.setStyleSheet(f"font-weight:700; color:{'#5a3a00' if sel else ORANGE}; background:transparent;")
        for w in (self.ver, self.summary):
            w.setStyleSheet(f"color:{dark if sel else '#e6e8ee'}; background:transparent;")
        self.foot.setStyleSheet(f"color:{dark if sel else '#bdbdbd'}; background:transparent;")


class ExplorePage(QWidget):
    def __init__(self, ctx, win):
        super().__init__()
        self.ctx, self.win = ctx, win
        self.setStyleSheet(QSS)
        self._matches: list[dict] | None = None     # modo local: lista completa paginada aqui; None = paginação no servidor
        self._items: list[dict] = []                # itens da página exibida
        self._total = 0
        self._page = 1
        self._gen = 0                               # invalida respostas assíncronas antigas
        self._params: dict = {}
        self._rows: dict[str, ModRow] = {}
        self._releases: list[Release] = []
        self._detail: dict = {}
        self._name = ""
        self._fetching = False
        self._syncing = False
        self._thumb_token = [0]
        self._thumbs = _ThumbSignals()
        self._thumbs.ready.connect(self._thumb_ready)
        self._cat_checks: dict[str, QCheckBox] = {}
        self._tag_rows: dict[str, tuple[QCheckBox, QToolButton]] = {}
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(450)
        self._debounce.timeout.connect(self._start_search)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 12)
        top = QHBoxLayout()
        t = QLabel("Explorar Mods")
        t.setObjectName("h1")
        top.addWidget(t)
        top.addSpacing(20)
        top.addWidget(QLabel("Instalar no perfil:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(220)
        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        top.addWidget(self.profile_combo)
        top.addStretch()
        self.catalog_btn = QPushButton("Atualizar catálogo")
        self.catalog_btn.setToolTip("Catálogo local usado na busca sem login / offline")
        self.catalog_btn.clicked.connect(lambda: self.fetch_catalog(True))
        top.addWidget(self.catalog_btn)
        root.addLayout(top)
        self.status = QLabel()
        self.status.setObjectName("fmuted")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        body = QHBoxLayout()
        body.setSpacing(10)
        root.addLayout(body, 1)
        body.addWidget(self._build_filters())
        body.addWidget(self._build_center(), 1)
        body.addWidget(self._build_detail())

        self.popup = QListWidget(self)
        self.popup.setObjectName("tagpopup")
        self.popup.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        self.popup.setFocusPolicy(Qt.NoFocus)
        self.popup.setAttribute(Qt.WA_ShowWithoutActivating)
        self.popup.itemClicked.connect(lambda it: self._accept_suggestion(it.data(Qt.UserRole)))
        self.query.installEventFilter(self)

    # ---------- construção ----------
    def _build_filters(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("fpanel")
        panel.setFixedWidth(240)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        inner = QFrame()
        inner.setObjectName("finner")
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setWidget(inner)
        lay.addWidget(sc)
        il = QVBoxLayout(inner)
        il.setSpacing(5)
        h = QLabel("Categorias")
        h.setObjectName("fhead")
        il.addWidget(h)
        for key, label in CATEGORIES:
            cb = QCheckBox(label)
            cb.stateChanged.connect(lambda _=0: self._trigger(True))
            self._cat_checks[key] = cb
            il.addWidget(cb)
        il.addSpacing(8)
        ht = QLabel("Tags")
        ht.setObjectName("fhead")
        il.addWidget(ht)
        for tg in taglib.TAGS:
            row = QHBoxLayout()
            row.setSpacing(4)
            cb = QCheckBox(tg.label)
            cb.setToolTip(f"${tg.id}")
            ex = QToolButton()
            ex.setObjectName("fexcl")
            ex.setText("⊘")
            ex.setCheckable(True)
            ex.setToolTip(f"Excluir mods com a tag {tg.label} (-${tg.id})")
            cb.toggled.connect(lambda on, t=tg.id: self._tag_clicked(t, "inc", on))
            ex.toggled.connect(lambda on, t=tg.id: self._tag_clicked(t, "exc", on))
            row.addWidget(cb, 1)
            row.addWidget(ex)
            il.addLayout(row)
            self._tag_rows[tg.id] = (cb, ex)
        self.tag_note = QLabel("Filtro por tags usa a busca oficial do Portal, que exige usuário e token "
                               "(Configurações → Mod Portal).")
        self.tag_note.setObjectName("fmuted")
        self.tag_note.setWordWrap(True)
        il.addWidget(self.tag_note)
        il.addSpacing(8)
        h2 = QLabel("Filtros")
        h2.setObjectName("fhead")
        il.addWidget(h2)
        self.f_compat = QCheckBox("Somente compatíveis")
        self.f_compat.setChecked(True)
        self.f_compat.setToolTip("Esconde mods feitos para outra versão do Factorio que a do perfil")
        self.f_installed = QCheckBox("Só instalados no perfil")
        self.f_new = QCheckBox("Ocultar instalados")
        for cb in (self.f_compat, self.f_installed, self.f_new):
            cb.stateChanged.connect(lambda _=0: self._trigger(True))
            il.addWidget(cb)
        il.addStretch()
        return panel

    def _build_center(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("fpanel")
        lay = QVBoxLayout(panel)
        row = QHBoxLayout()
        lab = QLabel("Ordenar por:")
        lab.setObjectName("fhead")
        row.addWidget(lab)
        self.sort = QComboBox()
        for label, key in (("Relevância", "relevance"), ("Mais baixados", "downloads"),
                           ("Atualizados recentemente", "updated"), ("Em alta", "trending")):
            self.sort.addItem(label, key)
        self.sort.currentIndexChanged.connect(lambda _=0: self._trigger(True))
        row.addWidget(self.sort)
        self.query = QLineEdit()
        self.query.setPlaceholderText("🔎 Buscar…  dica: $trains  $trains $logistics  -$combat  cargo $trains")
        self.query.setClearButtonEnabled(True)
        self.query.textEdited.connect(self._text_edited)
        self.query.returnPressed.connect(lambda: self._trigger(True))
        row.addWidget(self.query, 1)
        go = QPushButton("Buscar")
        go.setObjectName("primary")
        go.clicked.connect(lambda: self._trigger(True))
        row.addWidget(go)
        lay.addLayout(row)
        self.list = QListWidget()
        self.list.setObjectName("flist")
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.currentItemChanged.connect(self._row_selected)
        lay.addWidget(self.list, 1)
        foot = QHBoxLayout()
        self.count_lbl = QLabel()
        foot.addWidget(self.count_lbl, 1)
        self.pager = QHBoxLayout()
        self.pager.setSpacing(3)
        foot.addLayout(self.pager)
        lay.addLayout(foot)
        return panel

    def _build_detail(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("fpanel")
        panel.setFixedWidth(430)
        lay = QVBoxLayout(panel)
        head = QHBoxLayout()
        self.d_title = QLabel("Selecione um mod")
        self.d_title.setObjectName("fhead")
        self.d_title.setWordWrap(True)
        head.addWidget(self.d_title, 1)
        self.install_btn = QPushButton("Instalar")
        self.install_btn.setObjectName("fgreen")
        self.install_btn.setEnabled(False)
        self.install_btn.clicked.connect(self.install)
        self.changelog_btn = QPushButton("Registro de mudanças")
        self.changelog_btn.setEnabled(False)
        self.changelog_btn.clicked.connect(self.show_changelog)
        head.addWidget(self.install_btn)
        head.addWidget(self.changelog_btn)
        lay.addLayout(head)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        inner = QFrame()
        inner.setObjectName("finner")
        sc.setWidget(inner)
        lay.addWidget(sc, 1)
        il = QVBoxLayout(inner)
        top = QHBoxLayout()
        self.d_desc = QLabel("")
        self.d_desc.setWordWrap(True)
        self.d_desc.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.d_desc.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.d_desc.setOpenExternalLinks(True)
        top.addWidget(self.d_desc, 1)
        self.d_img = QLabel()
        self.d_img.setFixedSize(144, 144)
        self.d_img.setScaledContents(True)
        top.addWidget(self.d_img, 0, Qt.AlignTop)
        il.addLayout(top)
        self.grid = QGridLayout()
        self.grid.setColumnStretch(1, 1)
        self.grid.setVerticalSpacing(1)
        self._cells: dict[str, QLabel] = {}
        for r, key in enumerate(("Status", "Versão", "Autor", "Categoria", "Tags", "Portal de mods", "Página inicial",
                                 "Código-fonte", "Versão do Factorio", "Dependências")):
            k = QLabel(key)
            k.setStyleSheet(f"background:{PANEL}; padding:6px 8px; border:1px solid {LINE};")
            v = QLabel("")
            v.setWordWrap(True)
            v.setOpenExternalLinks(True)
            v.setTextInteractionFlags(Qt.TextBrowserInteraction)
            v.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            v.setStyleSheet(f"background:{PANEL}; padding:6px 8px; border:1px solid {LINE};")
            k.setAlignment(Qt.AlignTop)
            self.grid.addWidget(k, r, 0)
            self.grid.addWidget(v, r, 1)
            self._cells[key] = v
        il.addLayout(self.grid)
        il.addWidget(QLabel("Versão (release):"))
        self.rel_combo = QComboBox()
        self.rel_combo.currentIndexChanged.connect(lambda _=0: self._render_release())
        il.addWidget(self.rel_combo)
        self.auth_note = QLabel()
        self.auth_note.setObjectName("fmuted")
        self.auth_note.setWordWrap(True)
        il.addWidget(self.auth_note)
        il.addStretch()
        return panel

    # ---------- estado ----------
    def _creds(self) -> tuple[str, str] | None:
        return self.ctx.auth.load()

    def refresh(self) -> None:
        cur = self.profile_combo.currentData()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for p in self.ctx.pm.list_profiles():
            self.profile_combo.addItem(p.name, p.id)
        self.profile_combo.setCurrentIndex(max(self.profile_combo.findData(cur), 0))
        self.profile_combo.blockSignals(False)
        has = self._creds() is not None
        self.auth_note.setText("" if has else "Sem credenciais do Mod Portal: dá para navegar, mas o download ficará em "
                               "“requer autenticação” (Configurações). ZIPs locais continuam funcionando.")
        self.tag_note.setVisible(not has)
        for cb, ex in self._tag_rows.values():
            cb.setEnabled(has)
            ex.setEnabled(has)
        if has:
            self._load_tag_counts()
        if not has and not self.ctx.portal.load_catalog():
            self.status.setText("Catálogo ainda não baixado. Clique em “Atualizar catálogo” (≈12 MB; uma vez por dia basta) "
                                "ou entre com seu token em Configurações para usar a busca oficial.")
            self._matches, self._page = [], 1
            self._render_items([], 0)
        else:
            self._update_category_counts()
            self._trigger(True)

    def select_profile(self, profile_id: str) -> None:
        self.refresh()
        i = self.profile_combo.findData(profile_id)
        if i >= 0:
            self.profile_combo.setCurrentIndex(i)

    def _profile(self):
        pid = self.profile_combo.currentData()
        return self.ctx.pm.get_profile(pid) if pid else None

    def _game_version(self) -> str | None:
        p = self._profile()
        inst = self.ctx.pm.get_install(p.install_id) if p else None
        return inst.version if inst else None

    def _installed_map(self) -> dict[str, str]:
        p = self._profile()
        return {m.name: m.version for m in self.ctx.pm.scan_mods(p)} if p else {}

    def _profile_changed(self) -> None:
        self._update_category_counts()
        if self._creds():
            self._load_tag_counts()
        self._trigger(True)

    def _update_category_counts(self) -> None:
        gv = self._game_version() if self.f_compat.isChecked() else None
        counts: dict[str, int] = {}
        for m in self.ctx.portal.load_catalog():
            if gv and game_compat(m["fv"], gv) == "no":
                continue
            counts[m["category"]] = counts.get(m["category"], 0) + 1
        for key, label in CATEGORIES:
            self._cat_checks[key].setText(f"{label}   {counts.get(key, 0)}" if counts else label)

    def _load_tag_counts(self) -> None:
        creds, gv, dep = self._creds(), self._game_version(), not self.f_compat.isChecked()
        ids = [t.id for t in taglib.TAGS]

        def done(counts: dict):
            for t in taglib.TAGS:
                if t.id in counts:
                    self._tag_rows[t.id][0].setText(f"{t.label}   {counts[t.id]}")

        run_async(lambda: self.ctx.portal.tag_counts(creds, ids, gv, dep), done, lambda e: None)

    # ---------- catálogo local (fallback) ----------
    def fetch_catalog(self, force: bool = False) -> None:
        if self._fetching:
            return
        age = self.ctx.portal.catalog_age()
        if not force and age is not None and age < 86400:
            return
        self._fetching = True
        self.catalog_btn.setEnabled(False)
        self.status.setText("Baixando catálogo do Mod Portal… (alguns segundos)")

        def done(n):
            self._fetching = False
            self.catalog_btn.setEnabled(True)
            self.status.setText(f"Catálogo atualizado: {n} mods.")
            self._update_category_counts()
            self._trigger(True)

        def failed(e):
            self._fetching = False
            self.catalog_btn.setEnabled(True)
            offline = isinstance(e, PortalOffline)
            self.status.setText(("Sem conexão com o Mod Portal. " if offline else f"Erro: {e}. ") +
                                ("Usando catálogo salvo." if self.ctx.portal.load_catalog() else
                                 "Nenhum catálogo salvo; a busca fica indisponível offline."))

        run_async(self.ctx.portal.refresh_catalog, done, failed)

    # ---------- comandos $tag, sidebar e autocomplete ----------
    def _tag_clicked(self, tag_id: str, kind: str, on: bool) -> None:
        if self._syncing:
            return
        cb, ex = self._tag_rows[tag_id]
        self._syncing = True
        if on and kind == "inc":
            ex.setChecked(False)
        if on and kind == "exc":
            cb.setChecked(False)
        self._syncing = False
        inc = [t for t, (c, _) in self._tag_rows.items() if c.isChecked()]
        exc = [t for t, (_, e) in self._tag_rows.items() if e.isChecked()]
        self.query.setText(taglib.replace_tag_tokens(self.query.text(), inc, exc))
        self._trigger(True)

    def _sync_sidebar(self, parsed: taglib.ParsedSearch) -> None:
        self._syncing = True
        for t, (cb, ex) in self._tag_rows.items():
            cb.setChecked(t in parsed.include)
            ex.setChecked(t in parsed.exclude)
        self._syncing = False

    def _text_edited(self, text: str) -> None:
        self._update_popup()
        self._debounce.start()

    def _update_popup(self) -> None:
        text, pos = self.query.text(), self.query.cursorPosition()
        start, tok = taglib.current_token(text, pos)
        if not (tok.startswith("$") or tok.startswith("-$")) or not self._creds():
            self.popup.hide()
            return
        prefix = tok[2:] if tok.startswith("-$") else tok[1:]
        others = taglib.parse_search(text[:start] + " " + text[pos:])
        sugg = taglib.suggest(prefix, set(others.include) | set(others.exclude))
        if not sugg or (len(sugg) == 1 and prefix == sugg[0].id):
            self.popup.hide()
            return
        self.popup.clear()
        for t in sugg:
            it = QListWidgetItem(f"${t.id}  —  {t.label}")
            it.setData(Qt.UserRole, t.id)
            self.popup.addItem(it)
        self.popup.setCurrentRow(0)
        self.popup.setFixedSize(max(self.query.width(), 280), min(len(sugg) * 26 + 6, 260))
        self.popup.move(self.query.mapToGlobal(QPoint(0, self.query.height() + 2)))
        self.popup.show()
        self.popup.raise_()

    def _accept_suggestion(self, tag_id: str | None) -> None:
        if not tag_id:
            return
        text, pos = self.query.text(), self.query.cursorPosition()
        start, tok = taglib.current_token(text, pos)
        new_tok = ("-$" if tok.startswith("-$") else "$") + tag_id + " "
        self.query.setText(text[:start] + new_tok + text[pos:].lstrip())
        self.query.setCursorPosition(start + len(new_tok))
        self.popup.hide()
        self._trigger(True)

    def eventFilter(self, obj, ev) -> bool:
        if obj is self.query and ev.type() == QEvent.KeyPress and self.popup.isVisible():
            k = ev.key()
            if k in (Qt.Key_Down, Qt.Key_Up):
                n = self.popup.count()
                self.popup.setCurrentRow((self.popup.currentRow() + (1 if k == Qt.Key_Down else -1)) % n)
                return True
            if k in (Qt.Key_Tab, Qt.Key_Return, Qt.Key_Enter):
                it = self.popup.currentItem()
                self._accept_suggestion(it.data(Qt.UserRole) if it else None)
                return True
            if k == Qt.Key_Escape:
                self.popup.hide()
                return True
        if obj is self.query and ev.type() == QEvent.FocusOut:
            QTimer.singleShot(150, self.popup.hide)
        return super().eventFilter(obj, ev)

    # ---------- busca ----------
    def _trigger(self, immediate: bool = False) -> None:
        self._debounce.stop()
        if immediate:
            self._start_search()
        else:
            self._debounce.start()

    def _filters_changed(self) -> None:   # compatibilidade com chamadas antigas
        self._trigger(True)

    def _categories(self) -> list[str]:
        return [k for k, cb in self._cat_checks.items() if cb.isChecked()]

    def _start_search(self) -> None:
        parsed = taglib.parse_search(self.query.text())
        self._sync_sidebar(parsed)
        self._gen += 1
        gen = self._gen
        creds = self._creds()
        cats = self._categories()
        gv = self._game_version()
        warn = f"Tag desconhecida ignorada: {', '.join('$' + u for u in parsed.unknown)}. " if parsed.unknown else ""
        inst_filter = self.f_installed.isChecked() or self.f_new.isChecked()
        if not creds:
            self._local_search(parsed, cats, warn + ("Filtros de tag precisam do login do Mod Portal (Configurações); "
                                                    "mostrando busca por texto. " if parsed.has_tags else ""))
            return
        params = dict(query=parsed.text, tags=parsed.include, exclude_tags=parsed.exclude, categories=cats,
                      sort=self.sort.currentData(), version=gv, show_deprecated=not self.f_compat.isChecked())
        self._params = params
        need_all = len(parsed.include) >= 2 or inst_filter
        self.status.setText(warn + "Buscando no Mod Portal…")

        def work():
            if need_all:
                return self.ctx.portal.search_api_all(creds, **params), None
            return self.ctx.portal.search_api(creds, page=1, page_size=PAGE, **params)

        def done(res):
            if gen != self._gen:
                return
            items, total = res
            if total is None:   # modo "tudo" (AND de tags / filtros de instalados): pagina localmente
                inst = self._installed_map()
                if self.f_installed.isChecked():
                    items = [m for m in items if m["name"] in inst]
                if self.f_new.isChecked():
                    items = [m for m in items if m["name"] not in inst]
                self._matches, self._page = items, 1
                self._show_local_page(warn + self._query_summary(parsed))
            else:
                self._matches, self._page = None, 1
                self._render_items(items, total)
                self.status.setText(warn + self._query_summary(parsed))

        def failed(e):
            if gen != self._gen:
                return
            if isinstance(e, AuthRequired):
                self._local_search(parsed, cats, warn + "O Portal recusou seu usuário/token; refaça o login em "
                                   "Configurações. Mostrando busca local por texto. ")
            elif isinstance(e, PortalOffline):
                self._local_search(parsed, cats, warn + "Sem conexão: usando o catálogo salvo (sem filtro de tags). ")
            else:
                self._matches, self._page = [], 1
                self._render_items([], 0)
                self.status.setText(f"Erro na busca: {e}")

        run_async(work, done, failed)

    def _query_summary(self, p: taglib.ParsedSearch) -> str:
        bits = []
        if p.include:
            bits.append("com " + ", ".join(f"${t}" for t in p.include) + (" (todas)" if len(p.include) > 1 else ""))
        if p.exclude:
            bits.append("sem " + ", ".join(f"${t}" for t in p.exclude))
        return "Busca oficial do Mod Portal" + (" — " + "; ".join(bits) if bits else "")

    def _local_search(self, parsed: taglib.ParsedSearch, cats: list[str], note: str) -> None:
        gv = self._game_version() if self.f_compat.isChecked() else None
        sort = self.sort.currentData()
        found = self.ctx.portal.search(parsed.text, gv, None, limit=100000,
                                       sort={"trending": "downloads"}.get(sort, sort))
        if cats:
            found = [m for m in found if m["category"] in cats]
        inst = self._installed_map()
        if self.f_installed.isChecked():
            found = [m for m in found if m["name"] in inst]
        if self.f_new.isChecked():
            found = [m for m in found if m["name"] not in inst]
        self._matches, self._page = found, 1
        age = self.ctx.portal.catalog_age()
        stamp = (f"Catálogo local de {time.strftime('%d/%m %H:%M', time.localtime(time.time() - age))}"
                 if age is not None else "Sem catálogo local")
        self._show_local_page(f"{note}{stamp}".strip())
        if age is None or age > 86400:
            self.fetch_catalog()

    def _show_local_page(self, status: str = "") -> None:
        matches = self._matches or []
        self._render_items(matches[(self._page - 1) * PAGE: self._page * PAGE], len(matches))
        if status:
            self.status.setText(status)

    def _goto(self, page: int) -> None:
        self._page = page
        if self._matches is not None:
            self._show_local_page()
            return
        gen, creds, params = self._gen, self._creds(), dict(self._params)

        def done(res):
            if gen == self._gen:
                self._render_items(res[0], res[1])

        run_async(lambda: self.ctx.portal.search_api(creds, page=page, page_size=PAGE, **params), done,
                  lambda e: self.status.setText(f"Erro ao carregar a página: {e}"))

    # ---------- renderização ----------
    def _render_items(self, items: list[dict], total: int) -> None:
        self._thumb_token[0] += 1
        self.list.clear()
        self._rows.clear()
        self._items, self._total = items, total
        inst = self._installed_map()
        for m in items:
            row = ModRow(m, inst.get(m["name"]))
            item = QListWidgetItem()
            item.setSizeHint(QSize(100, 104))
            item.setData(Qt.UserRole, m["name"])
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
            self._rows[m["name"]] = row
        self.count_lbl.setText(f"Foram encontrados {total} mods")
        self._build_pager(total)
        if items:
            job = _ThumbJob(self.ctx.portal, [(m["name"], m.get("thumb", "")) for m in items], self._thumb_token,
                            self._thumb_token[0], self._thumbs)
            QThreadPool.globalInstance().start(job)

    def _build_pager(self, total: int) -> None:
        while self.pager.count():
            w = self.pager.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        last = max(1, -(-total // PAGE))
        prev = QPushButton("◀")
        prev.setObjectName("fpage")
        prev.setEnabled(self._page > 1)
        prev.clicked.connect(lambda: self._goto(self._page - 1))
        self.pager.addWidget(prev)
        for pg in sorted({1, 2, self._page - 1, self._page, self._page + 1, last - 1, last}):
            if 1 <= pg <= last:
                b = QPushButton(str(pg))
                b.setObjectName("fpage")
                b.setCheckable(True)
                b.setChecked(pg == self._page)
                b.clicked.connect(lambda _=False, n=pg: self._goto(n))
                self.pager.addWidget(b)
        nxt = QPushButton("▶")
        nxt.setObjectName("fpage")
        nxt.setEnabled(self._page < last)
        nxt.clicked.connect(lambda: self._goto(self._page + 1))
        self.pager.addWidget(nxt)

    def _thumb_ready(self, name: str, path: str) -> None:
        row = self._rows.get(name)
        if row:
            row.set_pixmap(path)
        if name == self._name:
            pm = QPixmap(path)
            if not pm.isNull():
                self.d_img.setPixmap(pm)

    # ---------- detalhes ----------
    def _row_selected(self, cur: QListWidgetItem | None, prev: QListWidgetItem | None) -> None:
        if prev is not None and (w := self.list.itemWidget(prev)):
            w.set_selected(False)
        if cur is None:
            return
        w = self.list.itemWidget(cur)
        w.set_selected(True)
        name = cur.data(Qt.UserRole)
        m = next((x for x in self._items if x["name"] == name), None)
        if m is None:
            return
        self._name = name
        self._detail, self._releases = {}, []
        self.d_title.setText(m["title"] or name)
        self.d_desc.setText(html.escape(m["summary"]) + "<br><br><i>Carregando detalhes…</i>")
        self.rel_combo.clear()
        self.install_btn.setEnabled(False)
        self.changelog_btn.setEnabled(False)
        self.d_img.setPixmap(w.icon.pixmap() or placeholder_pixmap(name, 144))
        for v in self._cells.values():
            v.setText("")
        self._cells["Autor"].setText(html.escape(m["owner"]))
        self._cells["Categoria"].setText(html.escape(category_label(m["category"])))
        self._cells["Tags"].setText(self._tag_labels(m.get("tags", [])))
        run_async(lambda: self.ctx.portal.get_full(name), lambda d: self._details(name, d),
                  lambda e: self._details_failed(name, e))

    @staticmethod
    def _tag_labels(ids: list[str]) -> str:
        return html.escape(", ".join(taglib.BY_ID[t].label if t in taglib.BY_ID else t for t in ids)) or "—"

    def _details_failed(self, name: str, e: Exception) -> None:
        if name == self._name:
            self.d_desc.setText("Sem conexão com o Mod Portal: detalhes indisponíveis offline."
                                if isinstance(e, PortalOffline) else html.escape(f"Erro ao carregar detalhes: {e}"))

    def _details(self, name: str, d: dict) -> None:
        if name != self._name:
            return
        self._detail = d
        gv = self._game_version() or ""
        rels = [Release.from_api(name, r) for r in d.get("releases", []) if isinstance(r, dict)]
        rels.sort(key=lambda r: parse_version(r.version) or (0, 0, 0), reverse=True)
        self._releases = rels
        self.rel_combo.blockSignals(True)
        self.rel_combo.clear()
        for r in rels:
            c = game_compat(r.factorio_version, gv) if gv else "maybe"
            tag = {"ok": "compatível", "maybe": "possivelmente", "no": "incompatível"}[c]
            self.rel_combo.addItem(f"{r.version}  (Factorio {r.factorio_version or '?'} — {tag})", r)
        self.rel_combo.setCurrentIndex(next((i for i, r in enumerate(rels) if gv and game_compat(r.factorio_version, gv) != "no"), 0))
        self.rel_combo.blockSignals(False)
        desc = (d.get("description") or d.get("summary") or "").strip()
        if d.get("_from_cache"):
            desc = "[dados do cache local — sem conexão]\n" + desc
        self.d_desc.setText(html.escape(desc[:2500]).replace("\n", "<br>"))
        link = lambda u: (f'<a style="color:#6cb6ff" href="{html.escape(u, quote=True)}">{html.escape(u)}</a>'
                          if isinstance(u, str) and u.startswith(("https://", "http://")) else "")
        c = self._cells
        c["Portal de mods"].setText(link(f"https://mods.factorio.com/mod/{name}"))
        c["Página inicial"].setText(link(d.get("homepage", "")) or "—")
        src = d.get("source_url") or (f"https://github.com/{d['github_path']}" if d.get("github_path") else "")
        c["Código-fonte"].setText(link(src) or "—")
        c["Autor"].setText(html.escape(d.get("owner", "")))
        if d.get("tags") is not None:
            c["Tags"].setText(self._tag_labels(d.get("tags", [])))
        self.install_btn.setEnabled(bool(rels) and self._profile() is not None)
        self.changelog_btn.setEnabled(bool(d.get("changelog")))
        self._render_release()

    def _render_release(self) -> None:
        rel: Release | None = self.rel_combo.currentData()
        c = self._cells
        if rel is None:
            return
        installed = self._installed_map()
        cur = installed.get(rel.name)
        c["Status"].setText(f"Instalado ({html.escape(cur)})" if cur else "Não instalado")
        c["Versão"].setText(html.escape(rel.version))
        c["Versão do Factorio"].setText(html.escape(rel.factorio_version or "?"))
        inst = self.ctx.pm.get_install(self._profile().install_id) if self._profile() else None
        gv = parse_version(inst.version) if inst else None
        dlcs = installed_dlcs(inst) if inst else []
        lines = []
        for dep in parse_dependencies(rel.dependencies):
            txt = html.escape(f"{dep.name} {dep.constraint_text()}".strip())
            if dep.kind == "incompatible":
                bad = dep.name in installed
                lines.append(f'<span style="color:{"#ff6b6b" if bad else "#9a9a9a"}">✖ incompatível com {txt}</span>')
            elif dep.kind in ("optional", "hidden_optional"):
                lines.append(f'<span style="color:{ORANGE}">{txt} (opcional)</span>')
            elif dep.kind == "no_order":
                continue
            else:
                if dep.name in ("base", "core"):
                    ok = dep.accepts(gv)
                elif dep.name in ("elevated-rails", "quality", "space-age"):
                    ok = dep.name in dlcs
                else:
                    ok = dep.name in installed and dep.accepts(parse_version(installed[dep.name]))
                missing = "" if ok else " — será instalado" if dep.name not in ("base", "core", "elevated-rails", "quality", "space-age") else " — indisponível"
                color = "#e6e8ee" if ok else ("#ff6b6b" if "indisp" in missing else "#ff9d9d")
                lines.append(f'<span style="color:{color}">{"✔" if ok else "➜"} {txt}{missing}</span>')
        c["Dependências"].setText("<br>".join(lines) or "Nenhuma")

    def show_changelog(self) -> None:
        TextReportDialog(self, f"Registro de mudanças — {self._name}", str(self._detail.get("changelog", ""))).exec()

    # ---------- instalação ----------
    def install(self) -> None:
        p, rel = self._profile(), self.rel_combo.currentData()
        inst = self.ctx.pm.get_install(p.install_id) if p else None
        if not p or not inst or not rel:
            error(self, "Instalar", "Selecione um perfil com instalação válida e uma versão.")
            return
        if self.ctx.runner.is_profile_running(p.id):
            error(self, "Instalar", "O perfil está em execução no Factorio. Feche o jogo primeiro.")
            return
        installed = self.ctx.pm.scan_mods(p)
        self.install_btn.setEnabled(False)
        self.install_btn.setText("Resolvendo…")

        def work():
            return dependency_resolver.resolve_install(rel, installed, inst.version, installed_dlcs(inst),
                                                       self.ctx.portal.releases, p.pins)

        def reset():
            self.install_btn.setEnabled(True)
            self.install_btn.setText("Instalar")

        def done(plan):
            reset()
            creds = "" if self.ctx.auth.has_credentials() else \
                "\n\n⚠ Sem credenciais do Portal: os downloads ficarão em “requer autenticação”."
            if not plan.ok:
                TextReportDialog(self, "Não é possível instalar", plan.report()).exec()
                return
            if TextReportDialog(self, f"Instalar em “{p.name}”", plan.report() + creds, "Confirmar instalação").exec():
                for r in plan.to_install:
                    old = [m for m in installed if m.name == r.name]
                    self.ctx.downloads.enqueue(r, p.id, self.ctx.pm.mods_dir(p), replaces=old)
                self.win.goto(self.win.downloads)

        run_async(work, done, lambda e: (reset(), error(self, "Instalar", str(e))))
