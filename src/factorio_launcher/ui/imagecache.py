"""Cache de pixmaps: decodifica já reduzido (nunca mantém a imagem original na memória) e recorta no modo "cover"."""
from __future__ import annotations

import math
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (QBrush, QColor, QImage, QImageReader, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)

from . import tokens as T

_MAX = 160
_cache: "OrderedDict[tuple, QPixmap]" = OrderedDict()


def _put(key: tuple, pm: QPixmap) -> QPixmap:
    _cache[key] = pm
    _cache.move_to_end(key)
    while len(_cache) > _MAX:
        _cache.popitem(last=False)
    return pm


def _get(key: tuple) -> QPixmap | None:
    pm = _cache.get(key)
    if pm is not None:
        _cache.move_to_end(key)
    return pm


def clear() -> None:
    _cache.clear()


def cover_pixmap(path: Path | str, w: int, h: int, dpr: float = 1.0) -> QPixmap | None:
    """Imagem do disco escalada para cobrir w×h (px lógicos) com recorte central. None se ilegível."""
    p = Path(path)
    try:
        mtime = p.stat().st_mtime_ns
    except OSError:
        return None
    key = ("file", str(p), mtime, w, h, dpr)
    hit = _get(key)
    if hit is not None:
        return hit
    tw, th = int(w * dpr), int(h * dpr)
    rd = QImageReader(str(p))
    rd.setAutoTransform(True)
    src = rd.size()
    if not src.isValid():
        return None
    scale = max(tw / src.width(), th / src.height())
    if scale < 1:   # decodifica já reduzido (JPEG tem decodificação escalada eficiente)
        rd.setScaledSize(QSize(max(tw, math.ceil(src.width() * scale)), max(th, math.ceil(src.height() * scale))))
    img = rd.read()
    if img.isNull():
        return None
    if img.width() * th != img.height() * tw or img.width() < tw:
        img = img.scaled(tw, th, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x, y = max(0, (img.width() - tw) // 2), max(0, (img.height() - th) // 3)   # corte um pouco acima do centro
    pm = QPixmap.fromImage(img.copy(x, y, tw, th))
    pm.setDevicePixelRatio(dpr)
    return _put(key, pm)


def placeholder_banner(seed: str, tint: str, w: int, h: int, dpr: float = 1.0) -> QPixmap:
    """Banner industrial desenhado (esteira + engrenagens), usado quando não há imagem oficial/personalizada."""
    key = ("ph", seed, tint, w, h, dpr)
    hit = _get(key)
    if hit is not None:
        return hit
    tw, th = int(w * dpr), int(h * dpr)
    img = QImage(tw, th, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(tint)
    g = QLinearGradient(0, 0, tw, th)
    g.setColorAt(0, QColor.fromHsv(c.hue(), 110, 62))
    g.setColorAt(1, QColor("#10141b"))
    p.fillRect(0, 0, tw, th, g)
    # esteira: faixa escura com "dentes" amarelados
    belt_y = int(th * 0.70)
    p.fillRect(0, belt_y, tw, int(th * 0.16), QColor("#1a1f27"))
    pen = QPen(QColor(T.ORANGE)); pen.setWidthF(max(1.5, th * 0.012))
    p.setPen(pen)
    step = max(10, int(th * 0.11))
    for x in range(-step, tw + step, step):
        p.drawLine(x, belt_y + int(th * 0.03), x + step // 2, belt_y + int(th * 0.13))
    p.setPen(Qt.NoPen)
    # engrenagens
    def gear(cx, cy, r, teeth, color, alpha):
        col = QColor(color); col.setAlpha(alpha)
        path = QPainterPath()
        for i in range(teeth * 2):
            ang = math.pi * i / teeth
            rr = r if i % 2 == 0 else r * 0.80
            for a in (ang - math.pi / (teeth * 4), ang + math.pi / (teeth * 4)):
                pt = QPointF(cx + rr * math.cos(a), cy + rr * math.sin(a))
                path.moveTo(pt) if path.isEmpty() else path.lineTo(pt)
        path.closeSubpath()
        p.setBrush(QBrush(col)); p.drawPath(path)
        p.setBrush(QColor(16, 20, 27, 230)); p.drawEllipse(QPointF(cx, cy), r * 0.30, r * 0.30)
    h0 = sum(map(ord, seed)) % 40
    gear(tw * (0.22 + h0 / 400), th * 0.38, th * 0.30, 10, "#FF9617", 90)
    gear(tw * 0.74, th * 0.30, th * 0.22, 8, "#5B7DB8", 80)
    gear(tw * 0.55, th * 0.66, th * 0.14, 7, "#FFAD42", 70)
    rg = QRadialGradient(tw * 0.5, th * 0.4, tw * 0.7)
    rg.setColorAt(0, QColor(0, 0, 0, 0)); rg.setColorAt(1, QColor(0, 0, 0, 110))
    p.fillRect(0, 0, tw, th, rg)
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return _put(key, pm)


def rounded(pm: QPixmap, radius: int, top_only: bool = False) -> QPixmap:
    dpr = pm.devicePixelRatio() or 1.0
    out = QPixmap(pm.size())
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    w, h = pm.width() / dpr, pm.height() / dpr
    if top_only:
        r = float(radius)
        path.moveTo(0, h)
        path.lineTo(0, r)
        path.arcTo(QRectF(0, 0, 2 * r, 2 * r), 180, -90)
        path.lineTo(w - r, 0)
        path.arcTo(QRectF(w - 2 * r, 0, 2 * r, 2 * r), 90, -90)
        path.lineTo(w, h)
        path.closeSubpath()
    else:
        path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    p.setClipPath(path)
    p.drawPixmap(0, 0, pm)
    p.end()
    return out
