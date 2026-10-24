"""Design tokens do launcher: única fonte de cores, tamanhos e tipografia (a Biblioteca e o tema global usam daqui)."""
from __future__ import annotations

# ---- cores ----
BG = "#101318"
SIDEBAR = "#171B23"
CARD = "#202632"
SURFACE = "#252D39"       # superfícies elevadas
SURFACE_HOVER = "#2B3544"
BORDER = "#343D4B"
BORDER_SOFT = "#2A3240"
ORANGE = "#FF9617"
ORANGE_HOVER = "#FFAD42"
ORANGE_PRESSED = "#E5830C"
ORANGE_DIM = "#4A3414"
ORANGE_ON = "#1A1205"     # texto sobre laranja
BLUE = "#518DFF"
BLUE_BG = "#1F3158"
GREEN = "#42C984"
GREEN_BG = "#173A2B"
RED = "#EF5B5B"
RED_BG = "#451D22"
TEXT = "#F4F5F7"
TEXT_MUTED = "#A1ADBF"
TEXT_DISABLED = "#667085"

# ---- tipografia ----
FONT_FAMILY = "Segoe UI"
FS_XS, FS_SM, FS_MD, FS_LG, FS_XL, FS_H1 = 11, 12, 13, 15, 18, 30

# ---- geometria ----
RADIUS_SM, RADIUS_MD, RADIUS_LG = 6, 8, 12
SIDEBAR_W = 230
CARD_W, CARD_H = 308, 356
CARD_GAP = 18
BANNER_H = 128
PANEL_W = 396
PANEL_DOCK_MIN_W = 1040   # abaixo disso o painel vira "gaveta" sobreposta
ANIM_MS = 180

# ---- badges: (texto, fundo, borda) ----
BADGE_STYLES = {
    "orange": (ORANGE, ORANGE_DIM, "#7A5214"),
    "blue": ("#8FB4FF", BLUE_BG, "#2F4F8F"),
    "green": (GREEN, GREEN_BG, "#256B4A"),
    "gray": (TEXT_MUTED, SURFACE, BORDER),
    "red": (RED, RED_BG, "#7A2F36"),
}
