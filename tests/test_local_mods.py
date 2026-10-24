import json
import zipfile

import pytest

from factorio_launcher.services import local_mods
from factorio_launcher.services.local_mods import ModError, read_zip_info


def test_reads_info_without_extracting(mkzip):
    info = read_zip_info(mkzip("Cool_Mod", "0.3.1", deps=["base >= 2.0"]))
    assert info["name"] == "Cool_Mod" and info["version"] == "0.3.1"


def test_info_at_root_without_folder(mkzip):
    assert read_zip_info(mkzip("Flat", "1.0.0", folder=False))["name"] == "Flat"


def test_malformed_zip(tmp_path):
    p = tmp_path / "bad.zip"
    p.write_bytes(b"PK\x03\x04garbage")
    with pytest.raises(ModError):
        read_zip_info(p)


def test_no_info_json(tmp_path):
    p = tmp_path / "n.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("x/readme.txt", "hi")
    with pytest.raises(ModError, match="info.json"):
        read_zip_info(p)


def test_path_traversal_rejected(tmp_path):
    p = tmp_path / "t.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("m_1.0.0/info.json", json.dumps({"name": "m", "version": "1.0.0"}))
        z.writestr("m_1.0.0/../../evil.lua", "x")
    with pytest.raises(ModError, match="inseguro"):
        read_zip_info(p)


@pytest.mark.parametrize("bad", [{"name": "../x", "version": "1.0.0"}, {"name": "a", "version": "1.0"},
                                 {"name": "a/b", "version": "1.0.0"}, {"version": "1.0.0"}, {"name": "a"}])
def test_invalid_info_fields(tmp_path, bad):
    p = tmp_path / "i.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("x/info.json", json.dumps(bad))
    with pytest.raises(ModError):
        read_zip_info(p)


def test_bad_json(tmp_path):
    p = tmp_path / "j.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("x/info.json", "{nope")
    with pytest.raises(ModError, match="malformado"):
        read_zip_info(p)


def test_write_failure_cleans_part(tmp_path, mkzip, monkeypatch):
    import shutil
    mods = tmp_path / "mods"
    monkeypatch.setattr(shutil, "copyfile", lambda *a, **k: (_ for _ in ()).throw(OSError("sem espaço")))
    with pytest.raises(ModError, match="Falha ao gravar"):
        local_mods.install_zip(mkzip("M", "1.0.0"), mods)
    assert not list(mods.glob("*.part")) and not list(mods.glob("*.zip"))


def test_dev_folder_import(tmp_path):
    src = tmp_path / "devmod"
    src.mkdir()
    (src / "info.json").write_text(json.dumps({"name": "dev", "version": "0.0.1"}))
    mods = tmp_path / "mods"
    m = local_mods.install_folder(src, mods)
    assert m.is_dir and (mods / "dev_0.0.1" / "info.json").is_file() and src.exists()
    assert local_mods.scan_mods(mods)[0].name == "dev"


def test_remove_cannot_escape(tmp_path):
    from factorio_launcher.models.entities import ModInfo
    mods = tmp_path / "mods"
    mods.mkdir()
    victim = tmp_path / "victim.zip"
    victim.write_text("x")
    with pytest.raises(ModError):
        local_mods.remove_mod(mods, ModInfo("v", "1.0.0", filename="../victim.zip"))
    assert victim.exists()
