import hashlib, os, subprocess, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from factorio_launcher.services import install_detector
from factorio_launcher.services.profile_manager import ProfileManager
from factorio_launcher.services.game_runner import build_args
from factorio_launcher.models.entities import SAVE_EXCLUSIVE

real = Path(os.environ["APPDATA"]) / "Factorio"
def snap():
    out = {}
    for p in real.rglob("*"):
        if p.is_file():
            st = p.stat(); out[str(p)] = (st.st_size, st.st_mtime_ns)
    return out
before = snap()
installs = install_detector.detect_installs()
print("detectadas:", [(i.version, i.path) for i in installs])
inst = next(i for i in installs if i.version.startswith("2.0"))
pm = ProfileManager(Path(".smoke_data"), real)
pm.add_install(inst)
p = pm.create_profile("RealCheck", inst, SAVE_EXCLUSIVE)
print(pm.config_file(p).read_text()[:300])
args = build_args(inst, pm.mods_dir(p), pm.config_file(p), ["--create", "smoke-save"])
print(args)
r = subprocess.run(args, capture_output=True, text=True, timeout=180, shell=False, encoding="utf-8", errors="replace")
print("rc", r.returncode); print((r.stdout or "")[-600:]); print((r.stderr or "")[-600:])
print("saves do perfil:", [x.name for x in pm.list_saves(p)])
print("arquivos userdata:", sorted(x.name for x in (pm.profile_root(p.id) / "userdata").iterdir()))
after = snap()
print("APPDATA/Factorio alterado:", before != after, [k for k in set(before)|set(after) if before.get(k) != after.get(k)][:10])
