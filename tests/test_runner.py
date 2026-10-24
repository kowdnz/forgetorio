from pathlib import Path

import pytest

from factorio_launcher.services.game_runner import GameRunner, LaunchError, build_args


class FakePopen:
    def __init__(self, args, **kw):
        self.args, self.kw = args, kw

    def poll(self):
        return None


def test_build_args_exact(fake_install, tmp_path):
    args = build_args(fake_install, tmp_path / "m ods", tmp_path / "c" / "config.ini", ["--load-game", "x"])
    assert args == [fake_install.exe, "--mod-directory", str(tmp_path / "m ods"), "--config",
                    str(tmp_path / "c" / "config.ini"), "--load-game", "x"]


def test_launch_uses_list_no_shell_and_paths_with_spaces(pm, fake_install):
    p = pm.create_profile("Run", fake_install)
    seen = {}

    def popen(args, **kw):
        seen["args"], seen["kw"] = args, kw
        return FakePopen(args, **kw)

    r = GameRunner(pid_lister=lambda: [], popen=popen)
    r.launch(p, fake_install, pm.mods_dir(p), pm.config_file(p))
    assert isinstance(seen["args"], list) and seen["kw"]["shell"] is False
    assert seen["args"][1] == "--mod-directory" and seen["args"][2] == str(pm.mods_dir(p))
    assert seen["args"][3] == "--config" and seen["args"][4] == str(pm.config_file(p))
    assert r.is_profile_running(p.id) and p.last_played


def test_launch_blocked_when_running(pm, fake_install):
    p = pm.create_profile("Run", fake_install)
    r = GameRunner(pid_lister=lambda: [123], popen=FakePopen)
    with pytest.raises(LaunchError, match="já está em execução"):
        r.launch(p, fake_install, pm.mods_dir(p), pm.config_file(p))


def test_launch_missing_exe_and_config(pm, fake_install, tmp_path):
    p = pm.create_profile("Run", fake_install)
    r = GameRunner(pid_lister=lambda: [], popen=FakePopen)
    pm.config_file(p).unlink()
    with pytest.raises(LaunchError, match="config.ini"):
        r.launch(p, fake_install, pm.mods_dir(p), pm.config_file(p))
    fake_install.exe = str(tmp_path / "nope.exe")
    with pytest.raises(LaunchError, match="Executável"):
        r.launch(p, fake_install, pm.mods_dir(p), pm.config_file(p))


def test_popen_oserror(pm, fake_install):
    p = pm.create_profile("Run", fake_install)

    def boom(*a, **k):
        raise OSError("bloqueado")

    with pytest.raises(LaunchError, match="Falha ao iniciar"):
        GameRunner(pid_lister=lambda: [], popen=boom).launch(p, fake_install, pm.mods_dir(p), pm.config_file(p))


def test_global_mods_dir_never_touched(pm, fake_install, tmp_path):
    glob = tmp_path / "fake-appdata" / "Factorio"
    p = pm.create_profile("G", fake_install)
    GameRunner(pid_lister=lambda: [], popen=FakePopen).launch(p, fake_install, pm.mods_dir(p), pm.config_file(p))
    assert not glob.exists()
