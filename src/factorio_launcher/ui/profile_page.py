from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from ..models.entities import SAVE_EXCLUSIVE, SAVE_SHARED, Profile
from ..services import backups, config_manager, dependency_resolver, local_mods, steam_cloud
from ..services.download_manager import DONE
from ..services.portal_client import PortalError, PortalOffline, game_compat
from ..services.profile_manager import ProfileError
from ..models.versions import parse_version
from .common import confirm, error, h1, human_size, info, muted, open_folder
from .dialogs import EXCL_WARN, SHARED_WARN, TextReportDialog
from .library_page import launch_profile
from .workers import run_async


class ProfilePage(QWidget):
    def __init__(self, ctx, win):
        super().__init__()
        self.ctx, self.win = ctx, win
        self.p: Profile | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 20, 28, 16)
        back = QPushButton("← Biblioteca")
        back.clicked.connect(lambda: win.goto(win.library))
        back.setFixedWidth(130)
        lay.addWidget(back)
        head = QHBoxLayout()
        self.title = h1("")
        head.addWidget(self.title)
        head.addStretch()
        self.play = QPushButton("▶  JOGAR")
        self.play.setObjectName("primary")
        self.play.clicked.connect(self.on_play)
        head.addWidget(self.play)
        for text, fn, name in (("Renomear", self.rename, ""), ("Duplicar", self.duplicate, ""),
                               ("Excluir", self.delete, "danger")):
            b = QPushButton(text)
            if name:
                b.setObjectName(name)
            b.clicked.connect(fn)
            head.addWidget(b)
        lay.addLayout(head)
        self.subtitle = muted()
        lay.addWidget(self.subtitle)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self._build_mods_tab()
        self._build_saves_tab()
        self._build_settings_tab()
        self._build_backup_tab()

    # ---------- util ----------
    def show_profile(self, profile_id: str) -> None:
        self.p = self.ctx.pm.get_profile(profile_id)
        if self.p is None:
            self.win.goto(self.win.library)
            return
        self.refresh()

    def refresh(self) -> None:
        if not self.p:
            return
        self.p = self.ctx.pm.get_profile(self.p.id) or self.p
        inst = self.ctx.pm.get_install(self.p.install_id)
        self.title.setText(self.p.name)
        mode = "saves exclusivos" if self.p.save_mode == SAVE_EXCLUSIVE else "saves compartilhados"
        self.subtitle.setText(f"Factorio {inst.version if inst else '— instalação ausente'}  •  {mode}  •  "
                              f"ID {self.p.id[:8]}")
        self.play.setEnabled(inst is not None)
        self.refresh_mods()
        self.refresh_saves()
        self.refresh_settings()
        self.refresh_backups()

    def _busy_check(self) -> bool:
        if self.p and self.ctx.runner.is_profile_running(self.p.id):
            error(self, "Perfil em execução", "O Factorio está rodando com este perfil. Feche o jogo antes de "
                  "alterar mods, saves ou backups.")
            return True
        return False

    def on_play(self) -> None:
        if self.p and launch_profile(self.ctx, self, self.p):
            self.refresh()

    def rename(self) -> None:
        name, ok = QInputDialog.getText(self, "Renomear perfil", "Novo nome:", text=self.p.name)
        if ok:
            try:
                self.ctx.pm.rename_profile(self.p, name)
                self.refresh()
            except ProfileError as e:
                error(self, "Renomear", str(e))

    def duplicate(self) -> None:
        name, ok = QInputDialog.getText(self, "Duplicar perfil", "Nome da cópia:", text=f"{self.p.name} (cópia)")
        if not ok:
            return
        copy_saves = False
        if self.p.save_mode == SAVE_EXCLUSIVE and self.ctx.pm.list_saves(self.p):
            copy_saves = confirm(self, "Duplicar", "Copiar também os saves exclusivos deste perfil?")
        try:
            q = self.ctx.pm.duplicate_profile(self.p, name, copy_saves)
        except (ProfileError, OSError) as e:
            error(self, "Duplicar", str(e))
            return
        self.win.open_profile(q.id)

    def delete(self) -> None:
        n_saves = len(self.ctx.pm.list_saves(self.p)) if self.p.save_mode == SAVE_EXCLUSIVE else 0
        extra = (f"\n\nATENÇÃO: este perfil tem {n_saves} save(s) exclusivo(s) que serão APAGADOS junto. "
                 f"Crie um backup com saves antes, se precisar.") if n_saves else ""
        if self.p.save_mode == SAVE_SHARED:
            extra = "\n\nOs saves compartilhados NÃO serão apagados."
        if not confirm(self, "Excluir perfil", f"Excluir o perfil “{self.p.name}” e seus mods?{extra}", danger=True):
            return
        if n_saves and not confirm(self, "Confirmar exclusão de saves",
                                   f"Confirma apagar definitivamente {n_saves} save(s) exclusivos?", danger=True):
            return
        if self._busy_check():
            return
        try:
            self.ctx.pm.delete_profile(self.p)
        except (ProfileError, OSError) as e:
            error(self, "Excluir", str(e))
            return
        self.p = None
        self.win.goto(self.win.library)

    def on_job(self, job) -> None:
        if self.p and job.profile_id == self.p.id and job.status == DONE and self.isVisible():
            self.refresh_mods()

    # ---------- aba Mods ----------
    def _build_mods_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        for text, fn in (("Instalar ZIP…", self.add_zip), ("Mod em desenvolvimento (pasta)…", self.add_folder),
                         ("Importar da pasta atual do Factorio…", self.import_current),
                         ("Procurar no Mod Portal", lambda: self.win.explore_for(self.p.id))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        lay.addLayout(bar)
        bar2 = QHBoxLayout()
        for text, fn in (("Remover", self.remove_selected), ("Fixar/Soltar versão", self.toggle_pin),
                         ("Verificar atualizações", self.check_updates), ("Diagnóstico", self.diagnose),
                         ("Abrir pasta de mods", lambda: open_folder(self.ctx.pm.mods_dir(self.p)))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar2.addWidget(b)
        bar2.addStretch()
        lay.addLayout(bar2)
        self.mod_table = QTableWidget(0, 6)
        self.mod_table.setHorizontalHeaderLabels(["Ativo", "Mod", "Versão", "Fixada", "Factorio", "Dependências"])
        self.mod_table.verticalHeader().setVisible(False)
        self.mod_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.mod_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.mod_table.setAlternatingRowColors(True)
        hh = self.mod_table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        self.mod_table.itemChanged.connect(self._mod_toggled)
        lay.addWidget(self.mod_table, 1)
        self.mod_status = muted()
        lay.addWidget(self.mod_status)
        self.tabs.addTab(w, "Mods")
        self._mods: list = []

    def refresh_mods(self) -> None:
        self._mods = self.ctx.pm.scan_mods(self.p)
        t = self.mod_table
        t.blockSignals(True)
        t.setRowCount(len(self._mods))
        for r, m in enumerate(self._mods):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if m.enabled else Qt.Unchecked)
            t.setItem(r, 0, chk)
            t.setItem(r, 1, QTableWidgetItem(m.title if m.title == m.name else f"{m.title}  ({m.name})"))
            t.setItem(r, 2, QTableWidgetItem(m.version + ("  [pasta]" if m.is_dir else "")))
            t.setItem(r, 3, QTableWidgetItem("📌" if m.pinned else ""))
            t.setItem(r, 4, QTableWidgetItem(m.factorio_version))
            t.setItem(r, 5, QTableWidgetItem(", ".join(m.dependencies)))
        t.blockSignals(False)
        names = {m.name for m in self._mods}
        dups = len(self._mods) - len(names)
        self.mod_status.setText(f"{len(self._mods)} mods neste perfil"
                                + (f"  •  ⚠ {dups} mod(s) com mais de uma versão instalada" if dups else "")
                                + ("" if self._mods else "  •  Nenhum mod instalado. Use “Instalar ZIP…” ou o Mod Portal."))

    def _mod_toggled(self, item: QTableWidgetItem) -> None:
        if item.column() != 0 or self._busy_check():
            self.refresh_mods()
            return
        m = self._mods[item.row()]
        try:
            local_mods.set_enabled(self.ctx.pm.mods_dir(self.p), m.name, item.checkState() == Qt.Checked)
        except local_mods.ModError as e:
            error(self, "Mod", str(e))
        self.refresh_mods()

    def _selected_mods(self) -> list:
        rows = sorted({i.row() for i in self.mod_table.selectedIndexes()})
        return [self._mods[r] for r in rows]

    def add_zip(self) -> None:
        if self._busy_check():
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Escolha ZIPs de mods", "", "Mods (*.zip)")
        errs, ok = [], 0
        for f in files:
            try:
                self.ctx.pm.install_zip(self.p, Path(f))
                ok += 1
            except local_mods.ModError as e:
                errs.append(f"{Path(f).name}: {e}")
        self.refresh_mods()
        if errs:
            error(self, "Alguns ZIPs não foram instalados", "\n".join(errs))
        if ok and not errs:
            info(self, "Mods", f"{ok} mod(s) instalado(s) somente neste perfil.")

    def add_folder(self) -> None:
        if self._busy_check():
            return
        d = QFileDialog.getExistingDirectory(self, "Pasta do mod (contém info.json)")
        if d:
            try:
                local_mods.install_folder(Path(d), self.ctx.pm.mods_dir(self.p))
                self.refresh_mods()
            except (local_mods.ModError, OSError) as e:
                error(self, "Mod em desenvolvimento", str(e))

    def import_current(self) -> None:
        if self._busy_check():
            return
        src = self.ctx.pm.system_factorio / "mods"
        if not confirm(self, "Importar mods",
                       f"Copiar os ZIPs de:\n{src}\npara este perfil?\n\nA pasta original NÃO será alterada nem esvaziada."):
            return
        try:
            done, skipped = self.ctx.pm.import_system_mods(self.p)
        except ProfileError as e:
            error(self, "Importar", str(e))
            return
        self.refresh_mods()
        info(self, "Importação", f"{len(done)} copiados, {len(skipped)} ignorados." +
             ("\n\n" + "\n".join(skipped[:15]) if skipped else ""))

    def remove_selected(self) -> None:
        sel = self._selected_mods()
        if not sel or self._busy_check():
            return
        if not confirm(self, "Remover mods", "Remover do perfil:\n" + "\n".join(f"• {m.name} {m.version}" for m in sel)):
            return
        for m in sel:
            try:
                local_mods.remove_mod(self.ctx.pm.mods_dir(self.p), m)
                self.p.pins.pop(m.name, None)
            except (local_mods.ModError, OSError) as e:
                error(self, "Remover", str(e))
        self.ctx.pm.save_profile(self.p)
        self.refresh_mods()

    def toggle_pin(self) -> None:
        for m in self._selected_mods():
            if self.p.pins.get(m.name) == m.version:
                del self.p.pins[m.name]
            else:
                self.p.pins[m.name] = m.version
        self.ctx.pm.save_profile(self.p)
        self.refresh_mods()

    def diagnose(self) -> None:
        inst = self.ctx.pm.get_install(self.p.install_id)
        if inst is None:
            error(self, "Diagnóstico", "Instalação do Factorio ausente.")
            return
        from ..services.install_detector import installed_dlcs
        probs = dependency_resolver.check_profile(self.ctx.pm.scan_mods(self.p), inst.version, installed_dlcs(inst))
        text = ("Nenhum problema de dependência encontrado entre os mods habilitados.\n"
                "(Mods opcionais e ordem de carga não são verificados.)") if not probs else "\n".join("✖ " + p for p in probs)
        TextReportDialog(self, f"Diagnóstico — {self.p.name}", text).exec()

    def check_updates(self) -> None:
        inst = self.ctx.pm.get_install(self.p.install_id)
        mods = [m for m in self._mods if not m.is_dir]
        if inst is None or not mods:
            info(self, "Atualizações", "Nada para verificar.")
            return
        self.mod_status.setText("Consultando o Mod Portal…")

        def work():
            found = []
            for m in mods:
                try:
                    rels = [r for r in self.ctx.portal.releases(m.name) if game_compat(r.factorio_version, inst.version) != "no"]
                except PortalError as e:
                    if isinstance(e, PortalOffline):
                        raise
                    continue  # mod local sem página no Portal
                cur = parse_version(m.version) or (0, 0, 0)
                newer = [r for r in rels if (parse_version(r.version) or (0, 0, 0)) > cur]
                if newer:
                    found.append((m, max(newer, key=lambda r: parse_version(r.version) or (0, 0, 0))))
            return found

        run_async(work, self._updates_found, lambda e: (self.refresh_mods(), error(self, "Atualizações", str(e))))

    def _updates_found(self, found) -> None:
        self.refresh_mods()
        if not found:
            info(self, "Atualizações", "Todos os mods estão atualizados (para esta versão do Factorio).")
            return
        free = [(m, r) for m, r in found if m.name not in self.p.pins]
        fixed = [(m, r) for m, r in found if m.name in self.p.pins]
        lines = [f"• {m.name}: {m.version} → {r.version}" for m, r in free]
        lines += [f"📌 {m.name}: fixado em {m.version} (há {r.version}; não será atualizado)" for m, r in fixed]
        if not free:
            TextReportDialog(self, "Atualizações", "\n".join(lines)).exec()
            return
        msg = "\n".join(lines) + ("\n\nUm backup dos mods será criado antes. Saves existentes podem ficar incompatíveis "
                                  "com versões novas dos mods; carregar um save em versão mais nova do jogo/mods pode "
                                  "ser irreversível.")
        if not TextReportDialog(self, "Atualizações disponíveis", msg, "Atualizar").exec():
            return
        inst = self.ctx.pm.get_install(self.p.install_id)
        from ..services.install_detector import installed_dlcs
        installed = self.ctx.pm.scan_mods(self.p)
        plans, problems = [], []
        for m, r in free:
            plan = dependency_resolver.resolve_install(r, installed, inst.version, installed_dlcs(inst),
                                                       self.ctx.portal.releases, self.p.pins)
            (plans if plan.ok else problems).append((m, r, plan))
        if problems:
            TextReportDialog(self, "Conflitos — nada foi atualizado",
                             "\n\n".join(f"{m.name} → {r.version}\n{pl.report()}" for m, r, pl in problems)).exec()
            return
        if self._busy_check():
            return
        backups.create_backup(self.ctx.pm.profile_root(self.p.id), label="antes-de-atualizar")
        for m, r, plan in plans:
            for rel in plan.to_install:
                old = [x for x in installed if x.name == rel.name]
                self.ctx.downloads.enqueue(rel, self.p.id, self.ctx.pm.mods_dir(self.p), replaces=old)
        self.win.goto(self.win.downloads)

    # ---------- aba Saves ----------
    def _build_saves_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.saves_info = muted()
        lay.addWidget(self.saves_info)
        self.saves_list = QListWidget()
        lay.addWidget(self.saves_list, 1)
        row = QHBoxLayout()
        b = QPushButton("Abrir pasta de saves")
        b.clicked.connect(lambda: open_folder(self.ctx.pm.saves_dir(self.p)))
        row.addWidget(b)
        row.addStretch()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Exclusivos", SAVE_EXCLUSIVE)
        self.mode_combo.addItem("Compartilhados", SAVE_SHARED)
        apply = QPushButton("Alterar modo de saves")
        apply.clicked.connect(self.change_mode)
        row.addWidget(self.mode_combo)
        row.addWidget(apply)
        lay.addLayout(row)
        self.tabs.addTab(w, "Saves")

    def refresh_saves(self) -> None:
        self.saves_list.clear()
        saves = self.ctx.pm.list_saves(self.p)
        local_names = {s.name for s in saves}
        for s in saves:
            st = s.stat()
            self.saves_list.addItem(f"{s.name}   •   {human_size(st.st_size)}   •   "
                                    f"{time.strftime('%d/%m/%Y %H:%M', time.localtime(st.st_mtime))}")
        cloud = steam_cloud.list_cloud_saves() if self.p.save_mode == SAVE_SHARED else []
        only_cloud = 0
        if cloud:
            self.saves_list.addItem("— ☁ Steam Cloud (inventário da última sincronização da Steam) —")
            for c in cloud:
                here = c.name in local_names
                only_cloud += not here
                self.saves_list.addItem(f"☁ {c.name}   •   {human_size(c.size)}   •   "
                                        f"{time.strftime('%d/%m/%Y %H:%M', time.localtime(c.mtime))}   •   "
                                        + ("também na pasta local ✔" if here else "só na nuvem (a Steam baixa ao sincronizar)"))
        d = self.ctx.pm.saves_dir(self.p)
        extra = ""
        if self.p.save_mode == SAVE_SHARED:
            extra = (f"\n☁ {len(cloud)} save(s) na Steam Cloud, {only_cloud} ainda não presentes na pasta local. "
                     "Lista somente leitura vinda do cache local da Steam; o launcher não baixa, envia nem altera nada da nuvem."
                     if cloud else "\nNenhum save da Steam Cloud encontrado neste PC (Steam/userdata/<conta>/427520).")
        self.saves_info.setText((EXCL_WARN if self.p.save_mode == SAVE_EXCLUSIVE else SHARED_WARN) +
                                f"\n\nPasta: {d}\n{len(saves)} save(s) local(is)." + extra +
                                ("\nSaves exclusivos não são enviados à Steam Cloud." if self.p.save_mode == SAVE_EXCLUSIVE else ""))
        i = self.mode_combo.findData(self.p.save_mode)
        self.mode_combo.setCurrentIndex(max(i, 0))

    def change_mode(self) -> None:
        new = self.mode_combo.currentData()
        if new == self.p.save_mode or self._busy_check():
            return
        if not confirm(self, "Alterar modo de saves",
                       "Os saves existentes NÃO serão movidos nem copiados; o perfil passará a usar outra pasta de "
                       "dados. Continuar?"):
            return
        try:
            self.ctx.pm.update_settings(self.p, save_mode=new)
        except (ProfileError, OSError) as e:
            error(self, "Saves", str(e))
        self.refresh()

    # ---------- aba Configurações ----------
    def _build_settings_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel("Instalação do Factorio:"))
        self.inst_combo = QComboBox()
        row.addWidget(self.inst_combo, 1)
        lay.addLayout(row)
        lay.addWidget(QLabel("Argumentos extras de linha de comando (opcional):"))
        self.extra = QLineEdit()
        lay.addWidget(self.extra)
        self.dev = QCheckBox("Perfil de desenvolvimento de mods (mostra o último erro de inicialização)")
        lay.addWidget(self.dev)
        lay.addWidget(QLabel("Pasta de dados compartilhada (só no modo compartilhado; vazio = padrão do Factorio):"))
        r2 = QHBoxLayout()
        self.shared_dir = QLineEdit()
        r2.addWidget(self.shared_dir, 1)
        br = QPushButton("Escolher…")
        br.clicked.connect(lambda: self.shared_dir.setText(QFileDialog.getExistingDirectory(self, "Pasta compartilhada") or self.shared_dir.text()))
        r2.addWidget(br)
        lay.addLayout(r2)
        save = QPushButton("Salvar configurações do perfil")
        save.setObjectName("primary")
        save.clicked.connect(self.save_settings)
        lay.addWidget(save)
        self.cfg_view = QPlainTextEdit()
        self.cfg_view.setReadOnly(True)
        lay.addWidget(muted("config.ini gerado para este perfil (a cópia do jogo nunca é alterada):"))
        lay.addWidget(self.cfg_view, 1)
        self.last_error = QPlainTextEdit()
        self.last_error.setReadOnly(True)
        self.last_error.setMaximumHeight(110)
        lay.addWidget(muted("Último erro registrado no log do jogo (desenvolvimento):"))
        lay.addWidget(self.last_error)
        refresh_err = QPushButton("Atualizar último erro")
        refresh_err.clicked.connect(self.refresh_last_error)
        lay.addWidget(refresh_err)
        self.tabs.addTab(w, "Configurações")

    def refresh_settings(self) -> None:
        self.inst_combo.clear()
        for i in self.ctx.pm.list_installs():
            self.inst_combo.addItem(f"Factorio {i.version} — {i.path}", i.id)
        self.inst_combo.setCurrentIndex(max(self.inst_combo.findData(self.p.install_id), 0))
        self.extra.setText(" ".join(self.p.extra_args))
        self.dev.setChecked(self.p.dev_mode)
        self.shared_dir.setText(self.p.shared_dir)
        cfg = self.ctx.pm.config_file(self.p)
        self.cfg_view.setPlainText(cfg.read_text(encoding="utf-8", errors="replace") if cfg.is_file() else "(ainda não gerado)")
        self.refresh_last_error()

    def save_settings(self) -> None:
        import shlex
        try:
            self.ctx.pm.update_settings(self.p, install_id=self.inst_combo.currentData() or self.p.install_id,
                                        extra_args=shlex.split(self.extra.text(), posix=False),
                                        dev_mode=self.dev.isChecked(), shared_dir=self.shared_dir.text().strip())
        except (ProfileError, ValueError, OSError) as e:
            error(self, "Configurações", str(e))
            return
        self.refresh()

    def refresh_last_error(self) -> None:
        log = config_manager.write_data_dir(self.p, self.ctx.pm.profile_root(self.p.id)) / "factorio-current.log"
        text = "(nenhum log encontrado ainda)"
        if log.is_file():
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            errs = [i for i, ln in enumerate(lines) if "Error" in ln or "error" in ln.lower()[:40]]
            text = "\n".join(lines[max(errs[-1] - 1, 0): errs[-1] + 6]) if errs else "Nenhum erro no último log. ✔"
        self.last_error.setPlainText(text)

    # ---------- aba Backup / Importar-Exportar ----------
    def _build_backup_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.backup_list = QListWidget()
        lay.addWidget(self.backup_list, 1)
        row = QHBoxLayout()
        self.bk_saves = QCheckBox("Incluir saves exclusivos")
        row.addWidget(self.bk_saves)
        for text, fn in (("Criar backup", self.make_backup), ("Restaurar selecionado", self.restore),
                         ("Abrir pasta de backups", lambda: open_folder(self.ctx.pm.profile_root(self.p.id) / "backups"))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        row2 = QHBoxLayout()
        for text, fn in (("Exportar lista de mods (modpack)…", self.export_pack), ("Importar lista de mods…", self.import_pack)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row2.addWidget(b)
        row2.addStretch()
        lay.addLayout(row2)
        lay.addWidget(muted("A lista exportada contém só nomes, versões e estados — nunca ZIPs de terceiros nem credenciais."))
        self.tabs.addTab(w, "Backup / Modpack")
        self._backups: list[Path] = []

    def refresh_backups(self) -> None:
        self._backups = backups.list_backups(self.ctx.pm.profile_root(self.p.id))
        self.backup_list.clear()
        for b in self._backups:
            self.backup_list.addItem(f"{b.name}   •   {human_size(b.stat().st_size)}")

    def make_backup(self) -> None:
        try:
            backups.create_backup(self.ctx.pm.profile_root(self.p.id), self.bk_saves.isChecked())
        except backups.BackupError as e:
            error(self, "Backup", str(e))
        self.refresh_backups()

    def restore(self) -> None:
        r = self.backup_list.currentRow()
        if r < 0 or self._busy_check():
            return
        saves = self.bk_saves.isChecked()
        if not confirm(self, "Restaurar backup",
                       "Os mods atuais serão substituídos pelos do backup" + (" e os saves exclusivos também" if saves else "") +
                       ". Um backup do estado atual é criado antes. Continuar?", danger=True):
            return
        try:
            backups.restore_backup(self.ctx.pm.profile_root(self.p.id), self._backups[r], saves)
        except backups.BackupError as e:
            error(self, "Restaurar", str(e))
        self.refresh()

    def export_pack(self) -> None:
        f, _ = QFileDialog.getSaveFileName(self, "Exportar modpack", f"{self.p.name}.modpack.json", "JSON (*.json)")
        if f:
            try:
                self.ctx.pm.export_modpack(self.p, Path(f))
            except OSError as e:
                error(self, "Exportar", str(e))

    def import_pack(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Importar modpack", "", "JSON (*.json)")
        if not f or self._busy_check():
            return
        try:
            data = self.ctx.pm.read_modpack(Path(f))
            missing = self.ctx.pm.apply_modpack_states(self.p, data)
        except ProfileError as e:
            error(self, "Importar", str(e))
            return
        self.refresh()
        info(self, "Modpack importado", "Estados e fixações aplicados aos mods já presentes." +
             (("\n\nMods ausentes (instale pelo Mod Portal ou ZIP):\n" + "\n".join(missing)) if missing else ""))
