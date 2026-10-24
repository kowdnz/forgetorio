from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QRadioButton, QVBoxLayout, QHBoxLayout)

from ..models.entities import SAVE_EXCLUSIVE, SAVE_SHARED, FactorioInstall, Profile

SHARED_WARN = ("Saves COMPARTILHADOS: usa a pasta de dados habitual do Factorio (saves, blueprints, player-data e "
               "logs são os mesmos do jogo normal e de outros perfis compartilhados). Os MODS continuam exclusivos do "
               "perfil. Cuidado: carregar um save com mods diferentes pode alterá-lo ao salvar.")
EXCL_WARN = ("Saves EXCLUSIVOS: o perfil usa sua própria pasta de dados (saves, blueprints, player-data, logs). "
             "Nada é copiado do jogo normal automaticamente. O login do Factorio dentro do jogo será pedido de novo.")


class NewProfileDialog(QDialog):
    def __init__(self, parent, installs: list[FactorioInstall], profiles: list[Profile]):
        super().__init__(parent)
        self.setWindowTitle("Novo perfil")
        self.setMinimumWidth(520)
        self._color = "#4f8cff"
        self.name = QLineEdit()
        self.name.setPlaceholderText("Ex.: Krastorio 2")
        self.install = QComboBox()
        for i in installs:
            self.install.addItem(f"Factorio {i.version} — {i.path}", i.id)
        self.template = QComboBox()
        self.template.addItem("Vazio (apenas jogo base / DLCs)", "empty")
        self.template.addItem("Importar mods da pasta atual do Factorio (cópia)", "import_current")
        if profiles:
            self.template.addItem("Duplicar perfil existente", "duplicate")
        self.source = QComboBox()
        for p in profiles:
            self.source.addItem(p.name, p.id)
        self.source.setEnabled(False)
        self.copy_saves = QCheckBox("Copiar também os saves exclusivos do perfil de origem")
        self.copy_saves.setEnabled(False)
        self.template.currentIndexChanged.connect(self._tpl)
        self.excl = QRadioButton("Saves exclusivos (recomendado)")
        self.shared = QRadioButton("Saves compartilhados")
        self.excl.setChecked(True)
        self.warn = QLabel(EXCL_WARN)
        self.warn.setWordWrap(True)
        self.warn.setObjectName("muted")
        self.excl.toggled.connect(lambda c: self.warn.setText(EXCL_WARN if c else SHARED_WARN))
        self.color_btn = QPushButton("Cor do cartão")
        self.color_btn.clicked.connect(self._pick)
        self._paint()
        form = QFormLayout()
        form.addRow("Nome", self.name)
        form.addRow("Instalação", self.install)
        form.addRow("Modelo", self.template)
        form.addRow("Origem", self.source)
        form.addRow("", self.copy_saves)
        form.addRow("Saves", self.excl)
        form.addRow("", self.shared)
        form.addRow("", self.warn)
        form.addRow("Cor", self.color_btn)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Criar")
        bb.button(QDialogButtonBox.Ok).setObjectName("primary")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(bb)

    def _tpl(self) -> None:
        dup = self.template.currentData() == "duplicate"
        self.source.setEnabled(dup)
        self.copy_saves.setEnabled(dup)

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self, "Cor do perfil")
        if c.isValid():
            self._color = c.name()
            self._paint()

    def _paint(self) -> None:
        self.color_btn.setStyleSheet(f"border-left: 14px solid {self._color};")

    def values(self) -> dict:
        return {"name": self.name.text(), "install_id": self.install.currentData(),
                "template": self.template.currentData(), "source_id": self.source.currentData(),
                "save_mode": SAVE_EXCLUSIVE if self.excl.isChecked() else SAVE_SHARED, "color": self._color,
                "copy_saves": self.copy_saves.isChecked()}


class TextReportDialog(QDialog):
    """Mostra um relatório (plano de instalação, diagnóstico) e pede confirmação opcional."""

    def __init__(self, parent, title: str, text: str, confirm_text: str | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(560, 380)
        box = QPlainTextEdit(text)
        box.setReadOnly(True)
        lay = QVBoxLayout(self)
        lay.addWidget(box)
        row = QHBoxLayout()
        row.addStretch()
        close = QPushButton("Fechar" if confirm_text is None else "Cancelar")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        if confirm_text:
            ok = QPushButton(confirm_text)
            ok.setObjectName("primary")
            ok.clicked.connect(self.accept)
            row.addWidget(ok)
        lay.addLayout(row)
