import io
import json
import os
import zipfile
from pathlib import Path

import pytest

from factorio_launcher.models.entities import FactorioInstall
from factorio_launcher.services.profile_manager import ProfileManager


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    """Nenhum teste pode enxergar ou tocar %APPDATA%/Factorio ou %LOCALAPPDATA% reais."""
    monkeypatch.setenv("FML_DATA_DIR", str(tmp_path / "launcher-data"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "fake-appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "fake-local"))


def make_mod_zip(path: Path, name="TestMod", version="1.0.0", deps=None, factorio_version="2.0", folder=True,
                 extra: dict | None = None) -> Path:
    info = {"name": name, "version": version, "title": name, "author": "t", "factorio_version": factorio_version}
    if deps is not None:
        info["dependencies"] = deps
    if extra:
        info.update(extra)
    prefix = f"{name}_{version}/" if folder else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(prefix + "info.json", json.dumps(info))
        z.writestr(prefix + "control.lua", "-- x")
    return path


@pytest.fixture
def mkzip(tmp_path):
    def _mk(name="TestMod", version="1.0.0", **kw):
        return make_mod_zip(tmp_path / "zips" / f"{name}_{version}.zip", name, version, **kw)
    return _mk


@pytest.fixture
def fake_install(tmp_path) -> FactorioInstall:
    root = tmp_path / "Jogos com espaço é" / "Factorio"
    (root / "bin" / "x64").mkdir(parents=True)
    exe = root / "bin" / "x64" / "factorio.exe"
    exe.write_bytes(b"MZ")
    (root / "data" / "base").mkdir(parents=True)
    (root / "data" / "base" / "info.json").write_text('{"name":"base","version":"2.0.77"}')
    return FactorioInstall.new(str(root), str(exe), "2.0.77")


@pytest.fixture
def pm(tmp_path, fake_install) -> ProfileManager:
    m = ProfileManager(tmp_path / "launcher-data", tmp_path / "fake-appdata" / "Factorio")
    m.add_install(fake_install)
    return m
