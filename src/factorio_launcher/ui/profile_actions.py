"""Ações de perfil compartilhadas entre a Biblioteca e a página de detalhes (duplicar, excluir, editar)."""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QColorDialog, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QPushButton, QVBoxLayout, QWidget)

from ..models.entities import SAVE_EXCLUSIVE, SAVE_SHARED, Profile
from ..services.profile_manager import ProfileError
from .banner_dialog import BannerDialog
from .common import confirm, error


def duplicate_profile(ctx, parent: QWidget, p: Profile) -> Profile | None:
    name, ok = QInputDialog.getText(parent, "Clonar perfil", "Nome da cópia:", text=f"{p.name} (cópia)")
    if not ok:
        return None
    copy_saves = False
    if p.save_mode == SAVE_EXCLUSIVE and ctx.pm.list_saves(p):
        copy_saves = confirm(parent, "Clonar", "Copiar também os saves exclusivos deste perfil?")
    try:
        return ctx.pm.duplicate_profile(p, name, copy_saves)
    except (ProfileError, OSError) as e:
        error(parent, "Clonar", str(e))
        return None


def delete_profile(ctx, parent: QWidget, p: Profile) -> bool:
    n_saves = len(ctx.pm.list_saves(p)) if p.save_mode == SAVE_EXCLUSIVE else 0
    extra = (f"\n\nATENÇÃO: este perfil tem {n_saves} save(s) exclusivo(s) que serão APAGADOS junto. "
             f"Crie um backup com saves antes, se precisar.") if n_saves else ""
    if p.save_mode == SAVE_SHARED:
        extra = "\n\nOs saves compartilhados NÃO serão apagados."
    if not confirm(parent, "Excluir perfil", f"Excluir o perfil “{p.name}” e seus mods?{extra}", danger=True):
        return False
    if n_saves and not confirm(parent, "Confirmar exclusão de saves",
                               f"Confirma apagar definitivamente {n_saves} save(s) exclusivos?", danger=True):
        return False
    if ctx.runner.is_profile_running(p.id):
        error(parent, "Perfil em execução", "O Factorio está rodando com este perfil. Feche o jogo antes de excluir.")
        return False
    try:
        ctx.pm.delete_profile(p)
    except (ProfileError, OSError) as e:
        error(parent, "Excluir", str(e))
        return False
    return True


class EditProfileDialog(QDialog):
    """Nome, cor e banner do perfil."""

    def __init__(self, ctx, parent: QWidget, p: Profile):
        super().__init__(parent)
        self.ctx, self.p = ctx, p
        self._color = p.color
        self.setWindowTitle("Editar perfil")
        self.setMinimumWidth(420)
        self.name = QLineEdit(p.name)
        self.color_btn = QPushButton("Escolher cor…")
        self.color_btn.clicked.connect(self._pick)
        self._paint()
        self.banner_btn = QPushButton("Alterar banner…")
        self.banner_btn.clicked.connect(lambda: BannerDialog(ctx, self, p).exec())
        form = QFormLayout()
        form.addRow("Nome", self.name)
        form.addRow("Cor do perfil", self.color_btn)
        form.addRow("Banner", self.banner_btn)
        hint = QLabel("Modo de saves, instalação e argumentos extras ficam em Detalhes → Configurações.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Salvar")
        bb.button(QDialogButtonBox.Save).setObjectName("primary")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hint)
        lay.addWidget(bb)

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self, "Cor do perfil")
        if c.isValid():
            self._color = c.name()
            self._paint()

    def _paint(self) -> None:
        self.color_btn.setStyleSheet(f"border-left: 16px solid {self._color};")

    def _save(self) -> None:
        try:
            self.ctx.pm.update_appearance(self.p, self.name.text(), self._color)
        except ProfileError as e:
            error(self, "Editar perfil", str(e))
            return
        self.accept()
