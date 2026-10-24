from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import QFrame, QLabel, QMessageBox, QWidget


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606 — abre o Explorer na pasta
    else:
        subprocess.Popen(["xdg-open", str(path)], shell=False)


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def confirm(parent: QWidget, title: str, text: str, danger: bool = False) -> bool:
    box = QMessageBox(QMessageBox.Warning if danger else QMessageBox.Question, title, text,
                      QMessageBox.Yes | QMessageBox.No, parent)
    box.button(QMessageBox.Yes).setText("Sim")
    box.button(QMessageBox.No).setText("Não")
    box.setDefaultButton(QMessageBox.No)
    return box.exec() == QMessageBox.Yes


def info(parent: QWidget, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


def error(parent: QWidget, title: str, text: str) -> None:
    QMessageBox.critical(parent, title, text)


def muted(text: str = "") -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("muted")
    lb.setWordWrap(True)
    return lb


def h1(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("h1")
    return lb


def card() -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    return f
