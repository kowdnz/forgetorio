import os, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from factorio_launcher.services import install_detector, dependency_resolver
from factorio_launcher.services.profile_manager import ProfileManager
from factorio_launcher.services.game_runner import build_args
from factorio_launcher.models.entities import SAVE_SHARED

real = Path(os.environ["APPDATA"]) / "Factorio"
def snap():
    return {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in real.rglob("*") if p.is_file()}
before = snap()
pm = ProfileManager(Path(".smoke_data"), real)
inst = next(i for i in pm.list_installs())
shared = Path(".smoke_data/shared-data").resolve()
p = pm.create_profile("SharedCheck", inst, SAVE_SHARED, shared_dir=str(shared))
done, skipped = pm.import_system_mods(p)  # le %APPDATA%/Factorio/mods (somente leitura)
print("importados:", len(done), "ignorados:", skipped[:3])
mods = pm.scan_mods(p)
print("diagnostico:", dependency_resolver.check_profile(mods, inst.version, install_detector.installed_dlcs(inst))[:5])
os.makedirs(".smoke_data/work", exist_ok=True)
args = build_args(inst, pm.mods_dir(p), pm.config_file(p), ["--create", str(Path(".smoke_data/shared-data/saves/shared-smoke").resolve())])
(shared / "saves").mkdir(parents=True, exist_ok=True)
r = subprocess.run(args, capture_output=True, text=True, timeout=300, shell=False, encoding="utf-8", errors="replace")
print("rc", r.returncode)
log = (shared / "factorio-current.log").read_text(encoding="utf-8", errors="replace")
print([l for l in log.splitlines() if "Write data path" in l or "Loading mod Bottleneck" in l or "Error" in l][:6])
print("save compartilhado:", [x.name for x in (shared / "saves").iterdir()])
print("APPDATA/Factorio alterado:", before != snap())
