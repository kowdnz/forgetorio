"""Gera src/factorio_launcher/assets/app.png e app.ico (engrenagem laranja + play)."""
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "src" / "factorio_launcher" / "assets"
S = 2048  # supersampling; reduzido para 1024 no final
C = S / 2


def vgrad(size, top, bottom):
    g = Image.linear_gradient("L").resize(size)
    return Image.composite(Image.new("RGB", size, bottom), Image.new("RGB", size, top), g)


def gear_mask(r_out, r_root, teeth=8):
    m = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(m)
    pts = []
    step = 2 * math.pi / teeth
    for i in range(teeth):
        a = i * step - step / 2
        # dente trapezoidal: base larga, topo mais estreito
        for frac, r in ((0.00, r_root), (0.17, r_root), (0.30, r_out), (0.70, r_out), (0.83, r_root)):
            ang = a + frac * step
            pts.append((C + r * math.cos(ang), C + r * math.sin(ang)))
    d.polygon(pts, fill=255)
    return m


def main():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # fundo: quadrado arredondado escuro
    pad, rad = int(S * 0.04), int(S * 0.22)
    bg = Image.new("L", (S, S), 0)
    ImageDraw.Draw(bg).rounded_rectangle((pad, pad, S - pad, S - pad), rad, fill=255)
    bg_rgb = vgrad((S, S), (52, 56, 64), (24, 26, 31))
    img.paste(bg_rgb, (0, 0), bg)

    # engrenagem laranja com gradiente
    gm = gear_mask(S * 0.43, S * 0.33)
    hole = Image.new("L", (S, S), 0)
    ImageDraw.Draw(hole).ellipse((C - S * 0.17, C - S * 0.17, C + S * 0.17, C + S * 0.17), fill=255)
    gm = ImageChops.subtract(gm, hole)

    # sombra
    sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sh.putalpha(gm.filter(ImageFilter.GaussianBlur(S * 0.012)).point(lambda v: int(v * 0.55)))
    img.alpha_composite(sh, (0, int(S * 0.015)))

    # contorno escuro + corpo
    edge = gm.filter(ImageFilter.MaxFilter(1 + 2 * int(S * 0.008)))
    img.paste(Image.new("RGB", (S, S), (120, 60, 8)), (0, 0), edge)
    img.paste(vgrad((S, S), (255, 190, 60), (232, 120, 14)), (0, 0), gm)

    # brilho interno (bisel): faixa clara no topo
    inner = gm.filter(ImageFilter.MinFilter(1 + 2 * int(S * 0.012)))
    rim = ImageChops.subtract(gm, inner)
    shifted = ImageChops.offset(rim, 0, int(S * 0.006))
    hi = ImageChops.multiply(rim, ImageChops.invert(shifted))
    img.paste(Image.new("RGB", (S, S), (255, 226, 140)), (0, 0), hi.point(lambda v: min(255, v * 2)))

    # miolo escuro
    core = Image.new("L", (S, S), 0)
    ImageDraw.Draw(core).ellipse((C - S * 0.255, C - S * 0.255, C + S * 0.255, C + S * 0.255), fill=255)
    core = ImageChops.subtract(core, hole.filter(ImageFilter.MaxFilter(1)))
    ring = Image.new("L", (S, S), 0)
    ImageDraw.Draw(ring).ellipse((C - S * 0.255, C - S * 0.255, C + S * 0.255, C + S * 0.255), outline=255, width=int(S * 0.012))
    img.paste(Image.new("RGB", (S, S), (122, 62, 10)), (0, 0), ring)

    # furo central -> fundo escuro com botão play
    hole_full = Image.new("L", (S, S), 0)
    ImageDraw.Draw(hole_full).ellipse((C - S * 0.17, C - S * 0.17, C + S * 0.17, C + S * 0.17), fill=255)
    img.paste(vgrad((S, S), (30, 32, 38), (16, 17, 20)), (0, 0), hole_full)
    r = S * 0.095
    tri = [(C - r * 0.7 + r * 0.18, C - r), (C - r * 0.7 + r * 0.18, C + r), (C + r * 1.05 + r * 0.18, C)]
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).polygon(tri, fill=(255, 170, 40, 255))
    g2 = glow.filter(ImageFilter.GaussianBlur(S * 0.02))
    img.alpha_composite(g2)
    d = ImageDraw.Draw(img)
    d.polygon(tri, fill=(255, 196, 70, 255))

    final = img.resize((1024, 1024), Image.LANCZOS)
    OUT.mkdir(parents=True, exist_ok=True)
    final.save(OUT / "app.png", optimize=True)
    final.save(OUT / "app.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)])
    print("ok")


if __name__ == "__main__":
    main()
