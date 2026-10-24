import zipfile

import pytest

from factorio_launcher.services import backups, install_detector, local_mods


def test_backup_restore_roundtrip(pm, fake_install, mkzip):
    p = pm.create_profile("B", fake_install)
    pm.install_zip(p, mkzip("M", "1.0.0"))
    (pm.saves_dir(p) / "s.zip").write_bytes(b"save1")
    root = pm.profile_root(p.id)
    b = backups.create_backup(root, include_saves=True, label="antes update")
    pm.install_zip(p, mkzip("N", "1.0.0"))
    (pm.saves_dir(p) / "s.zip").write_bytes(b"save2")
    backups.restore_backup(root, b, restore_saves=True)
    assert [m.name for m in pm.scan_mods(p)] == ["M"]
    assert (pm.saves_dir(p) / "s.zip").read_bytes() == b"save1"
    assert len(backups.list_backups(root)) == 2  # original + pre-restore


def test_restore_without_saves_keeps_saves(pm, fake_install, mkzip):
    p = pm.create_profile("B", fake_install)
    root = pm.profile_root(p.id)
    (pm.saves_dir(p) / "s.zip").write_bytes(b"A")
    b = backups.create_backup(root, include_saves=True)
    (pm.saves_dir(p) / "s.zip").write_bytes(b"B")
    backups.restore_backup(root, b, restore_saves=False)
    assert (pm.saves_dir(p) / "s.zip").read_bytes() == b"B"


def test_restore_rejects_traversal(pm, fake_install, tmp_path):
    p = pm.create_profile("B", fake_install)
    root = pm.profile_root(p.id)
    evil = root / "backups" / "evil.zip"
    evil.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("mods/../../../outside.txt", "x")
    with pytest.raises(backups.BackupError):
        backups.restore_backup(root, evil)
    assert not (tmp_path / "outside.txt").exists()


def test_resolve_root_variants(fake_install):
    from pathlib import Path
    root = Path(fake_install.path)
    assert install_detector.resolve_root(root) == root
    assert install_detector.resolve_root(root / "bin" / "x64") == root
    assert install_detector.resolve_root(root / "bin" / "x64" / "factorio.exe") == root
    assert install_detector.resolve_root(root / "data") is None


def test_validate_install_with_mocked_version(fake_install, monkeypatch):
    monkeypatch.setattr(install_detector, "read_version", lambda exe: ("2.0.77", "84539"))
    inst = install_detector.validate_install(fake_install.path)
    assert inst.version == "2.0.77" and inst.build == "84539"
    monkeypatch.setattr(install_detector, "read_version", lambda exe: None)
    assert install_detector.validate_install(fake_install.path) is None


def test_version_regex():
    m = install_detector._VERSION_RE.search("Version: 2.1.23 (build 87750, win64, steam)")
    assert m.groups() == ("2.1.23", "87750")


def test_dlc_detection(fake_install):
    from pathlib import Path
    assert install_detector.installed_dlcs(fake_install) == []
    d = Path(fake_install.path) / "data" / "space-age"
    d.mkdir()
    (d / "info.json").write_text("{}")
    assert install_detector.installed_dlcs(fake_install) == ["space-age"]


def test_steam_cloud_parse_and_list(tmp_path):
    from factorio_launcher.services import steam_cloud
    vdf = '''"427520"
{
	"ChangeNumber"		"1"
	"Factorio/saves/é trem.zip"
	{
		"root"		"4"
		"size"		"12227767"
		"time"		"1684179332"
		"syncstate"		"1"
	}
	"Factorio/saves/sub/x.zip"
	{
		"size"		"1"
	}
	"Factorio/config/config.ini"
	{
		"size"		"1"
	}
}'''
    acc = tmp_path / "userdata" / "123" / "427520"
    acc.mkdir(parents=True)
    (acc / "remotecache.vdf").write_text(vdf, encoding="utf-8")
    saves = steam_cloud.list_cloud_saves([tmp_path / "userdata"])
    assert [(s.name, s.size, s.account, s.synced) for s in saves] == [("é trem.zip", 12227767, "123", True)]
    assert steam_cloud.list_cloud_saves([tmp_path / "nope"]) == []
