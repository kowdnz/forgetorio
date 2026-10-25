from pathlib import Path

import pytest

from factorio_launcher.services.game_runner import GameRunner, LaunchError, SteamGameProcess, build_args


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


def test_steam_install_launches_via_steam_and_tracks_game(pm, fake_install, tmp_path, monkeypatch):
    steam_root = tmp_path / "Steam"
    steam_root.mkdir()
    steam_exe = steam_root / "steam.exe"
    steam_exe.write_bytes(b"MZ")
    monkeypatch.setattr("factorio_launcher.services.game_runner._steam_roots", lambda: [steam_root])
    game_root = tmp_path / "Other Library" / "steamapps" / "common" / "Factorio"
    game_exe = game_root / "bin" / "x64" / "factorio.exe"
    game_exe.parent.mkdir(parents=True)
    game_exe.write_bytes(b"MZ")
    fake_install.path, fake_install.exe = str(game_root), str(game_exe)
    p = pm.create_profile("Steam", fake_install)
    calls = []
    pids = []
    runner = GameRunner(pid_lister=lambda: pids, popen=lambda args, **kw: calls.append((args, kw)) or FakePopen(args, **kw))

    proc = runner.launch(p, fake_install, pm.mods_dir(p), pm.config_file(p))

    assert calls[0][0] == [str(steam_exe), "-applaunch", "427520", "--mod-directory",
                            str(pm.mods_dir(p)), "--config", str(pm.config_file(p))]
    assert calls[0][1]["cwd"] == str(steam_root)
    assert isinstance(proc, SteamGameProcess)
    assert runner.is_profile_running(p.id)
    pids.append(123)
    assert runner.is_profile_running(p.id)
    pids.clear()
    assert not runner.is_profile_running(p.id)
    assert proc.elapsed_seconds() >= 0


def test_non_managed_steam_folder_runs_own_exe(fake_install, tmp_path, monkeypatch):
    from factorio_launcher.services.game_runner import steam_exe_for_install
    steam_root = tmp_path / "Steam"
    steam_root.mkdir()
    (steam_root / "steam.exe").write_bytes(b"MZ")
    monkeypatch.setattr("factorio_launcher.services.game_runner._steam_roots", lambda: [steam_root])
    common = tmp_path / "Lib" / "steamapps" / "common"
    fake_install.path = str(common / "Factorio_2.0.76")
    assert steam_exe_for_install(fake_install) is None
    fake_install.path = str(common / "Factorio")
    assert steam_exe_for_install(fake_install) is not None


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
