import json
import zipfile
from pathlib import Path

import pytest

from factorio_launcher.models.entities import SAVE_EXCLUSIVE, SAVE_SHARED
from factorio_launcher.persistence.jsonstore import load_json, save_json
from factorio_launcher.services import config_manager, local_mods
from factorio_launcher.services.local_mods import ModError
from factorio_launcher.services.profile_manager import ProfileError


def test_two_profiles_independent_mods(pm, fake_install, mkzip):
    a = pm.create_profile("Krastorio", fake_install)
    b = pm.create_profile("Vanilla", fake_install)
    assert pm.mods_dir(a) != pm.mods_dir(b)
    assert (pm.mods_dir(a) / "mod-list.json").is_file() and (pm.mods_dir(b) / "mod-list.json").is_file()
    pm.install_zip(a, mkzip("Krastorio2", "2.0.0"))
    assert [m.name for m in pm.scan_mods(a)] == ["Krastorio2"]
    assert pm.scan_mods(b) == []
    assert "Krastorio2" in local_mods.read_mod_list(pm.mods_dir(a))
    assert "Krastorio2" not in local_mods.read_mod_list(pm.mods_dir(b))


def test_install_does_not_move_source_and_no_duplicates(pm, fake_install, mkzip):
    p = pm.create_profile("P", fake_install)
    z = mkzip("M", "1.2.3")
    pm.install_zip(p, z)
    assert z.exists()
    with pytest.raises(ModError):
        pm.install_zip(p, z)


def test_toggle_remove(pm, fake_install, mkzip):
    p = pm.create_profile("P", fake_install)
    pm.install_zip(p, mkzip("M", "1.0.0"))
    local_mods.set_enabled(pm.mods_dir(p), "M", False)
    assert local_mods.read_mod_list(pm.mods_dir(p))["M"] is False
    assert pm.scan_mods(p)[0].enabled is False
    local_mods.remove_mod(pm.mods_dir(p), pm.scan_mods(p)[0])
    assert pm.scan_mods(p) == [] and "M" not in local_mods.read_mod_list(pm.mods_dir(p))
    with pytest.raises(ModError):
        local_mods.set_enabled(pm.mods_dir(p), "core", False)


def test_duplicate_and_delete_leave_original_intact(pm, fake_install, mkzip):
    p = pm.create_profile("Orig", fake_install)
    pm.install_zip(p, mkzip("M", "1.0.0"))
    d = pm.duplicate_profile(p, "Copia")
    assert [m.name for m in pm.scan_mods(d)] == ["M"]
    local_mods.set_enabled(pm.mods_dir(d), "M", False)
    assert pm.scan_mods(p)[0].enabled is True
    pm.delete_profile(d)
    assert (pm.mods_dir(p) / "M_1.0.0.zip").is_file()
    assert pm.get_profile(d.id) is None


def test_unique_names_and_validation(pm, fake_install):
    pm.create_profile("A", fake_install)
    with pytest.raises(ProfileError):
        pm.create_profile("a", fake_install)
    with pytest.raises(ProfileError):
        pm.create_profile("  ", fake_install)


def test_exclusive_config(pm, fake_install):
    p = pm.create_profile("Ex", fake_install, SAVE_EXCLUSIVE)
    cfg = pm.config_file(p).read_text(encoding="utf-8")
    paths = config_manager.parse_paths(cfg)
    root = pm.profile_root(p.id)
    assert paths["write-data"] == str(root / "userdata").replace("\\", "/")
    assert paths["read-data"] == str(Path(fake_install.path) / "data").replace("\\", "/")
    assert (root / "userdata" / "saves").is_dir()


def test_shared_config_uses_system_dir_and_creates_nothing_there(pm, fake_install, tmp_path):
    p = pm.create_profile("Sh", fake_install, SAVE_SHARED)
    paths = config_manager.parse_paths(pm.config_file(p).read_text(encoding="utf-8"))
    assert paths["write-data"] == str(tmp_path / "fake-appdata" / "Factorio").replace("\\", "/")
    assert not (tmp_path / "fake-appdata").exists()  # perfil compartilhado não cria nada no diretório global
    assert not (pm.profile_root(p.id) / "userdata").exists()


def test_switch_save_mode_regenerates_config(pm, fake_install):
    p = pm.create_profile("S", fake_install, SAVE_SHARED)
    pm.update_settings(p, save_mode=SAVE_EXCLUSIVE)
    paths = config_manager.parse_paths(pm.config_file(p).read_text(encoding="utf-8"))
    assert paths["write-data"].endswith("/userdata")


def test_config_inherits_preferences_but_not_paths(pm, fake_install, tmp_path):
    base = tmp_path / "fake-appdata" / "Factorio" / "config"
    base.mkdir(parents=True)
    (base / "config.ini").write_text(
        "; version=13\n[path]\nread-data=C:/evil\nwrite-data=C:/evil2\n[general]\nlocale=pt-BR\n", encoding="utf-8")
    original = (base / "config.ini").read_text()
    p = pm.create_profile("C", fake_install)
    text = pm.config_file(p).read_text(encoding="utf-8")
    assert "locale=pt-BR" in text and "evil" not in text
    assert (base / "config.ini").read_text() == original  # original intocado


def test_delete_cannot_escape(pm, fake_install):
    p = pm.create_profile("X", fake_install)
    p.id = "..\\.."
    with pytest.raises(ProfileError):
        pm.delete_profile(p)


def test_rename(pm, fake_install):
    p = pm.create_profile("Old", fake_install)
    pm.rename_profile(p, "New")
    assert pm.get_profile(p.id).name == "New"


def test_import_system_mods_readonly_source(pm, fake_install, tmp_path):
    from conftest import make_mod_zip
    sysmods = tmp_path / "fake-appdata" / "Factorio" / "mods"
    make_mod_zip(sysmods / "A_1.0.0.zip", "A", "1.0.0")
    make_mod_zip(sysmods / "B_1.0.0.zip", "B", "1.0.0")
    (sysmods / "broken_1.0.0.zip").write_bytes(b"not a zip")
    (sysmods / "mod-list.json").write_text(json.dumps({"mods": [{"name": "A", "enabled": True}, {"name": "B", "enabled": False}]}))
    before = sorted(p.name for p in sysmods.iterdir())
    p = pm.create_profile("Imp", fake_install)
    done, skipped = pm.import_system_mods(p)
    assert sorted(done) == ["A_1.0.0.zip", "B_1.0.0.zip"] and len(skipped) == 1
    states = local_mods.read_mod_list(pm.mods_dir(p))
    assert states["A"] is True and states["B"] is False
    assert sorted(x.name for x in sysmods.iterdir()) == before


def test_modpack_export_import(pm, fake_install, mkzip, tmp_path):
    p = pm.create_profile("E", fake_install)
    pm.install_zip(p, mkzip("M", "1.0.0"))
    pm.export_modpack(p, tmp_path / "pack.json")
    text = (tmp_path / "pack.json").read_text()
    assert "token" not in text.lower() and ".zip" not in text
    q = pm.create_profile("F", fake_install)
    missing = pm.apply_modpack_states(q, pm.read_modpack(tmp_path / "pack.json"))
    assert missing == ["M 1.0.0"]
    (tmp_path / "bad.json").write_text("{}")
    with pytest.raises(ProfileError):
        pm.read_modpack(tmp_path / "bad.json")


def test_duplicate_copy_saves(pm, fake_install):
    p = pm.create_profile("S", fake_install, SAVE_EXCLUSIVE)
    (pm.saves_dir(p) / "a.zip").write_bytes(b"save")
    d = pm.duplicate_profile(p, "S2", copy_saves=True)
    assert (pm.saves_dir(d) / "a.zip").read_bytes() == b"save"
    d2 = pm.duplicate_profile(p, "S3", copy_saves=False)
    assert pm.list_saves(d2) == []


def test_json_store_atomic_and_corruption_fallback(tmp_path):
    f = tmp_path / "x.json"
    save_json(f, {"a": 1})
    save_json(f, {"a": 2})
    assert load_json(f)["a"] == 2 and load_json(f)["schema_version"] == 1
    f.write_text("{corrupt")
    assert load_json(f)["a"] == 1  # volta ao .bak
    assert load_json(tmp_path / "missing.json", {"k": 1}) == {"k": 1}


def test_write_failure_leaves_original(tmp_path, monkeypatch):
    f = tmp_path / "x.json"
    save_json(f, {"a": 1})
    import os
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        save_json(f, {"a": 2})
    monkeypatch.undo()
    assert load_json(f)["a"] == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_delete_with_locked_files_hides_profile_and_cleans_later(pm, fake_install, mkzip, monkeypatch, tmp_path):
    """WinError 32: o perfil some da lista, o app avisa e a sobra é apagada na próxima abertura."""
    import shutil
    from factorio_launcher.services.profile_manager import ProfileManager
    p = pm.create_profile("Travado", fake_install)
    pm.install_zip(p, mkzip("M", "1.0.0"))
    (pm.saves_dir(p) / "s.zip").write_bytes(b"x")
    root = pm.profile_root(p.id)

    def locked(path, *a, **k):
        raise PermissionError(32, "O arquivo já está sendo usado por outro processo", str(path))

    monkeypatch.setattr(shutil, "rmtree", locked)
    monkeypatch.setattr(ProfileManager, "_rmtree_retry", staticmethod(lambda r, tries=4, wait=0.5: "em uso"))
    msg = pm.delete_profile(p)
    assert msg and "removido da lista" in msg and "em uso" in msg
    assert pm.get_profile(p.id) is None and root.exists() and (root / ".deleting").is_file()
    monkeypatch.undo()
    other = pm.create_profile("Outro", fake_install)
    pm2 = ProfileManager(pm.data_dir, pm.system_factorio)          # "reinício": conclui a limpeza pendente
    assert not root.exists()
    assert pm2.get_profile(other.id) is not None                    # perfis normais intactos


def test_delete_retries_then_succeeds(pm, fake_install, monkeypatch):
    import shutil
    p = pm.create_profile("Retry", fake_install)
    real, calls = shutil.rmtree, {"n": 0}

    def flaky(path, *a, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(32, "em uso")
        return real(path, *a, **k)

    monkeypatch.setattr(shutil, "rmtree", flaky)
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert pm.delete_profile(p) is None and calls["n"] == 3
    assert not pm.profile_root(p.id).exists()


def test_purge_ignores_folders_without_marker(pm, fake_install):
    from factorio_launcher.services.profile_manager import ProfileManager
    stranger = pm.profiles_root / "algo-do-usuario"
    stranger.mkdir()
    (stranger / "arquivo.txt").write_text("não apagar")
    ProfileManager(pm.data_dir, pm.system_factorio)
    assert (stranger / "arquivo.txt").exists()


def test_pending_marker_survives_failed_cleanup(pm, fake_install, monkeypatch):
    """Regressão: o rmtree parcial apagava a própria marca e a sobra nunca era limpa."""
    from factorio_launcher.services.profile_manager import ProfileManager
    p = pm.create_profile("Marca", fake_install)
    root = pm.profile_root(p.id)

    def partial(r, tries=4, wait=0.5):
        for f in root.rglob("*"):
            if f.is_file():
                f.unlink()          # apaga tudo (inclusive a marca), deixando só a pasta "travada"
        return "em uso"

    monkeypatch.setattr(ProfileManager, "_rmtree_retry", staticmethod(partial))
    assert pm.delete_profile(p)
    assert (root / ".deleting").is_file()
    monkeypatch.undo()
    ProfileManager(pm.data_dir, pm.system_factorio)
    assert not root.exists()
