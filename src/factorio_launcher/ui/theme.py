"""Tema global (QSS) gerado a partir dos design tokens."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from . import tokens as T

# compatibilidade com módulos que ainda importam estes nomes
BG, PANEL, CARD, BORDER, TEXT, MUTED = T.BG, T.SIDEBAR, T.CARD, T.BORDER, T.TEXT, T.TEXT_MUTED
ACCENT, ACCENT_HOVER, GOOD, BAD = T.ORANGE, T.ORANGE_HOVER, T.GREEN, T.RED

QSS = f"""
* {{ font-family: '{T.FONT_FAMILY}'; font-size: {T.FS_MD}px; color: {T.TEXT}; }}
QMainWindow, QWidget#page, QDialog {{ background: {T.BG}; }}
QWidget#sidebar {{ background: {T.SIDEBAR}; border-right: 1px solid {T.BORDER_SOFT}; }}
QLabel#brand {{ font-size: {T.FS_LG}px; font-weight: 700; color: {T.ORANGE}; }}
QPushButton#nav {{ text-align: left; padding: 13px 18px 13px 20px; border: none; border-left: 3px solid transparent;
    background: transparent; color: {T.TEXT_MUTED}; font-size: 14px; border-radius: 0; }}
QPushButton#nav:hover {{ background: {T.SURFACE}; color: {T.TEXT}; }}
QPushButton#nav:checked {{ background: {T.ORANGE_DIM}; color: {T.TEXT}; border-left: 3px solid {T.ORANGE}; font-weight: 600; }}
QPushButton {{ background: {T.SURFACE}; border: 1px solid {T.BORDER}; border-radius: {T.RADIUS_MD}px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {T.ORANGE}; background: {T.SURFACE_HOVER}; }}
QPushButton:pressed {{ background: {T.CARD}; }}
QPushButton:disabled {{ color: {T.TEXT_DISABLED}; border-color: {T.BORDER_SOFT}; background: {T.CARD}; }}
QPushButton#primary {{ background: {T.ORANGE}; color: {T.ORANGE_ON}; font-weight: 700; border: none; }}
QPushButton#primary:hover {{ background: {T.ORANGE_HOVER}; }}
QPushButton#primary:pressed {{ background: {T.ORANGE_PRESSED}; }}
QPushButton#primary:disabled {{ background: {T.ORANGE_DIM}; color: #8a7a62; }}
QPushButton#danger {{ color: {T.RED}; }}
QFrame#card {{ background: {T.CARD}; border: 1px solid {T.BORDER_SOFT}; border-radius: {T.RADIUS_LG}px; }}
QFrame#banner {{ background: {T.ORANGE_DIM}; border: 1px solid {T.ORANGE}; border-radius: {T.RADIUS_MD}px; }}
QLabel#h1 {{ font-size: 22px; font-weight: 700; }}
QLabel#muted {{ color: {T.TEXT_MUTED}; }}
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {{ background: {T.SIDEBAR}; border: 1px solid {T.BORDER};
    border-radius: {T.RADIUS_MD}px; padding: 6px 8px; selection-background-color: {T.ORANGE}; selection-color: {T.ORANGE_ON}; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {T.ORANGE}; }}
QComboBox QAbstractItemView {{ background: {T.SURFACE}; border: 1px solid {T.BORDER}; selection-background-color: {T.ORANGE};
    selection-color: {T.ORANGE_ON}; outline: 0; }}
QTableView, QTableWidget, QListWidget {{ background: {T.SIDEBAR}; border: 1px solid {T.BORDER}; border-radius: {T.RADIUS_MD}px;
    gridline-color: {T.BORDER_SOFT}; alternate-background-color: #1b202a; selection-background-color: {T.ORANGE_DIM}; }}
QHeaderView::section {{ background: {T.CARD}; border: none; border-bottom: 1px solid {T.BORDER}; padding: 6px; color: {T.TEXT_MUTED}; }}
QTabWidget::pane {{ border: 1px solid {T.BORDER}; border-radius: {T.RADIUS_MD}px; top: -1px; }}
QTabBar::tab {{ background: transparent; padding: 9px 16px; color: {T.TEXT_MUTED}; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {T.TEXT}; border-bottom: 2px solid {T.ORANGE}; }}
QProgressBar {{ background: {T.SIDEBAR}; border: 1px solid {T.BORDER}; border-radius: 5px; text-align: center; height: 16px; }}
QProgressBar::chunk {{ background: {T.ORANGE}; border-radius: 4px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {T.BORDER}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #46526a; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {T.BORDER}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QToolTip {{ background: {T.SURFACE}; color: {T.TEXT}; border: 1px solid {T.BORDER}; padding: 4px; }}
QMenu {{ background: {T.SURFACE}; border: 1px solid {T.BORDER}; border-radius: {T.RADIUS_MD}px; padding: 6px; }}
QMenu::item {{ padding: 8px 22px 8px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {T.ORANGE_DIM}; }}
QMenu::separator {{ height: 1px; background: {T.BORDER}; margin: 5px 6px; }}
QMessageBox {{ background: {T.BG}; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in ((QPalette.Window, T.BG), (QPalette.WindowText, T.TEXT), (QPalette.Base, T.SIDEBAR),
                        (QPalette.AlternateBase, "#1b202a"), (QPalette.Text, T.TEXT), (QPalette.Button, T.SURFACE),
                        (QPalette.ButtonText, T.TEXT), (QPalette.Highlight, T.ORANGE), (QPalette.HighlightedText, T.ORANGE_ON),
                        (QPalette.ToolTipBase, T.SURFACE), (QPalette.ToolTipText, T.TEXT)):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setFont(QFont(T.FONT_FAMILY, 10))
    app.setStyleSheet(QSS)
