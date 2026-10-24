"""Gera capturas reais da Biblioteca em pasta temporária (nunca toca em dados do usuário).

Uso: python tools/visual_check.py <pasta_saida> [--no-download]
Usa rede para baixar as imagens oficiais (cache em <saida>/data/assets) e COPIA (somente leitura na origem) alguns
ZIPs de mods/saves de %APPDATA%/Factorio para os perfis de teste.
"""
import os
import shutil
import sys
import time
from pathlib import Path

out = Path(sys.argv[1]).resolve()
out.mkdir(parents=True, exist_ok=True)
os.environ["FML_DATA_DIR"] = str(out / "data")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from factorio_launcher.app import AppContext  # noqa: E402
from factorio_launcher.models.entities import SAVE_EXCLUSIVE, SAVE_SHARED  # noqa: E402
from factorio_launcher.services import install_detector  # noqa: E402
from factorio_launcher.ui.main_window import MainWindow  # noqa: E402
from factorio_launcher.ui.theme import apply_theme  # noqa: E402

app = QApplication([])
apply_theme(app)
ctx = AppContext()
real = Path(os.environ["APPDATA"]) / "Factorio"


def pump(sec):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.02)


if "--no-download" not in sys.argv:
    n, errs = ctx.pm.assets.download_official(lambda i, t, title: print(f"  baixando {i}/{t} {title}", end="\r"))
    print(f"\nimagens baixadas: {n}, erros: {errs[:3]}")

for i in install_detector.detect_installs():
    ctx.pm.add_install(i)
inst = next(i for i in ctx.pm.list_installs() if i.version.startswith("2.0"))
a = ctx.pm.create_profile("Krastorio 2", inst, SAVE_EXCLUSIVE, color="#c0392b")
b = ctx.pm.create_profile("Vanilla", inst, SAVE_SHARED, color="#2980b9", shared_dir=str(out / "shared"))
c = ctx.pm.create_profile("Space Exploration", inst, SAVE_EXCLUSIVE, color="#8e44ad")
d = ctx.pm.create_profile("Teste sem instalação", inst, SAVE_SHARED, color="#16a085", shared_dir=str(out / "shared"))
for z in sorted((real / "mods").glob("*.zip"))[:21]:
    ctx.pm.install_zip(a, z)
for s in sorted((real / "saves").glob("*.zip"), key=lambda f: f.stat().st_mtime)[-4:]:
    shutil.copy2(s, ctx.pm.saves_dir(a) / s.name)
a.last_played, a.play_seconds, a.favorite = "2026-10-21T20:00:00", 48 * 3600 + 600, True
ctx.pm.save_profile(a)
ctx.pm.set_official_banner(a, "sa-gleba") if ctx.pm.assets.image_path("sa-gleba") else None
ctx.pm.set_official_banner(c, "sa-aquilo") if ctx.pm.assets.image_path("sa-aquilo") else None
(d_inst := ctx.pm.get_install(d.install_id))
d.install_id = "inexistente"
ctx.pm.save_profile(d)

win = MainWindow(ctx)
win.resize(int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 1672, 940)
win.show()
win.goto(win.library)
pump(1.5)
win.library.select(a.id)
pump(3.5)
win.grab().save(str(out / "library_1672.png"))
for w, h in ((1366, 768), (1100, 700), (900, 640)):
    win.resize(w, h)
    pump(1.2)
    win.grab().save(str(out / f"library_{w}.png"))
win.resize(1672, 940)
pump(0.8)
win.library.close_panel(animate=False)
pump(0.8)
win.grab().save(str(out / "library_no_panel.png"))
win.library.search.setText("zzzz")
pump(0.8)
win.grab().save(str(out / "library_no_results.png"))
print("capturas em", out)
