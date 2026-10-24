from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPlainTextEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from .. import __version__, paths
from ..services import install_detector
from ..services.auth_store import AuthError, read_player_data_credentials
from ..services.profile_manager import ProfileError
from .common import card, confirm, error, h1, info, muted, open_folder
from .workers import run_async


class SettingsPage(QWidget):
    def __init__(self, ctx, win):
        super().__init__()
        self.ctx, self.win = ctx, win
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 16)
        outer.addWidget(h1("Configurações"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        lay = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # --- instalações
        c1 = card()
        l1 = QVBoxLayout(c1)
        l1.addWidget(QLabel("<b>Instalações do Factorio</b>"))
        self.installs = QListWidget()
        self.installs.setMaximumHeight(120)
        l1.addWidget(self.installs)
        row = QHBoxLayout()
        for text, fn in (("Detectar automaticamente", self.detect), ("Adicionar manualmente…", self.add_manual),
                         ("Remover selecionada", self.remove)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        l1.addLayout(row)
        self.inst_status = muted()
        l1.addWidget(self.inst_status)
        lay.addWidget(c1)

        # --- autenticação
        c2 = card()
        l2 = QVBoxLayout(c2)
        l2.addWidget(QLabel("<b>Mod Portal — autenticação para downloads</b>"))
        l2.addWidget(muted("Downloads do Portal exigem seu usuário e token do factorio.com (o token fica no Cofre de "
                           "Credenciais do Windows; nunca em arquivos do launcher). Sem isso, navegação e ZIPs locais "
                           "continuam funcionando."))
        r = QHBoxLayout()
        self.user = QLineEdit()
        self.user.setPlaceholderText("Usuário")
        self.token = QLineEdit()
        self.token.setPlaceholderText("Token (não é a senha)")
        self.token.setEchoMode(QLineEdit.Password)
        r.addWidget(self.user)
        r.addWidget(self.token)
        l2.addLayout(r)
        r2 = QHBoxLayout()
        for text, fn in (("Salvar", self.save_creds), ("Importar do player-data.json do Factorio…", self.import_creds),
                         ("Esquecer credenciais", self.clear_creds)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            r2.addWidget(b)
        r2.addStretch()
        l2.addLayout(r2)
        self.auth_status = muted()
        l2.addWidget(self.auth_status)
        lay.addWidget(c2)

        # --- dados / diagnóstico
        c3 = card()
        l3 = QVBoxLayout(c3)
        l3.addWidget(QLabel("<b>Dados, logs e diagnóstico</b>"))
        l3.addWidget(muted(f"Dados do launcher: {ctx.data_dir}\nOs dados do Factorio original em "
                           f"{paths.system_factorio_dir()} são apenas lidos (nunca alterados)."))
        r3 = QHBoxLayout()
        for text, fn in (("Abrir pasta de dados", lambda: open_folder(ctx.data_dir)),
                         ("Abrir pasta de logs", lambda: open_folder(paths.logs_dir())), ("Gerar diagnóstico", self.diagnostic)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            r3.addWidget(b)
        r3.addStretch()
        l3.addLayout(r3)
        self.diag = QPlainTextEdit()
        self.diag.setReadOnly(True)
        self.diag.setMaximumHeight(180)
        l3.addWidget(self.diag)
        lay.addWidget(c3)
        lay.addStretch()

    def refresh(self) -> None:
        self.installs.clear()
        for i in self.ctx.pm.list_installs():
            self.installs.addItem(f"Factorio {i.version} (build {i.build or '?'}) — {i.path}")
        creds = self.ctx.auth.load()
        if creds:
            self.user.setText(creds[0])
        self.auth_status.setText(("✔ Credenciais salvas no cofre do Windows." if creds else "Sem credenciais.") +
                                 ("" if self.ctx.auth.secure_storage_available else
                                  " (cofre indisponível: a sessão guarda o token só em memória)"))

    # ---------- instalações ----------
    def detect(self) -> None:
        self.inst_status.setText("Procurando…")

        def done(found):
            for i in found:
                self.ctx.pm.add_install(i)
            self.inst_status.setText(f"{len(found)} instalação(ões) encontrada(s)." if found else
                                     "Nada encontrado nos locais padrão. Use “Adicionar manualmente”.")
            self.refresh()

        run_async(install_detector.detect_installs, done, lambda e: self.inst_status.setText(f"Erro: {e}"))

    def add_manual(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Pasta do Factorio (contém bin/x64/factorio.exe)")
        if not d:
            return
        self.inst_status.setText("Validando…")

        def done(inst):
            if inst is None:
                self.inst_status.setText("")
                error(self, "Instalação inválida", "Não encontrei bin/x64/factorio.exe ou não consegui obter a versão "
                      "(--version).")
                return
            self.ctx.pm.add_install(inst)
            self.inst_status.setText(f"Adicionada: Factorio {inst.version}")
            self.refresh()

        run_async(install_detector.validate_install, done, lambda e: error(self, "Erro", str(e)), d)

    def remove(self) -> None:
        r = self.installs.currentRow()
        if r < 0:
            return
        inst = self.ctx.pm.list_installs()[r]
        try:
            self.ctx.pm.remove_install(inst.id)
        except ProfileError as e:
            error(self, "Remover", str(e))
        self.refresh()

    # ---------- credenciais ----------
    def save_creds(self) -> None:
        try:
            self.ctx.auth.save(self.user.text().strip(), self.token.text().strip())
        except AuthError as e:
            error(self, "Credenciais", str(e))
            return
        self.token.clear()
        self.refresh()

    def import_creds(self) -> None:
        if not confirm(self, "Importar credenciais",
                       "O launcher vai ler o usuário e o token do arquivo player-data.json do seu Factorio e guardá-los "
                       "no Cofre de Credenciais do Windows. O arquivo original não é alterado. Autorizar?"):
            return
        creds = read_player_data_credentials()
        if not creds:
            error(self, "Importar", "Não encontrei service-username/service-token em player-data.json "
                  "(faça login no Factorio uma vez).")
            return
        try:
            self.ctx.auth.save(*creds)
        except AuthError as e:
            error(self, "Credenciais", str(e))
        self.refresh()

    def clear_creds(self) -> None:
        self.ctx.auth.clear()
        self.user.clear()
        self.token.clear()
        self.refresh()

    # ---------- diagnóstico ----------
    def diagnostic(self) -> None:
        lines = [f"Factorio Modpack Launcher {__version__}", f"Dados: {self.ctx.data_dir}"]
        for i in self.ctx.pm.list_installs():
            ok = Path(i.exe).is_file()
            lines.append(f"Instalação: {i.version} {i.path} — exe {'OK' if ok else 'AUSENTE'}")
        for p in self.ctx.pm.list_profiles():
            lines.append(f"Perfil “{p.name}”: {len(self.ctx.pm.scan_mods(p))} mods, saves {p.save_mode}, "
                         f"config {'OK' if self.ctx.pm.config_file(p).is_file() else 'AUSENTE'}")
        lines.append(f"Credenciais do Portal: {'sim' if self.ctx.auth.has_credentials() else 'não'} (valores nunca exibidos)")
        lines.append(f"Catálogo local: {len(self.ctx.portal.load_catalog())} mods")
        self.diag.setPlainText("\n".join(lines))
