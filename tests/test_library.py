import io
import json
import os
import time
import zipfile
from pathlib import Path

import httpx
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402

from conftest import make_mod_zip  # noqa: E402
from factorio_launcher.app import AppContext  # noqa: E402
from factorio_launcher.models.entities import SAVE_EXCLUSIVE, SAVE_SHARED, Profile  # noqa: E402
from factorio_launcher.services import asset_service as A  # noqa: E402
from factorio_launcher.services import local_mods  # noqa: E402
from factorio_launcher.services.profile_manager import ProfileError  # noqa: E402
from factorio_launcher.ui.main_window import MainWindow  # noqa: E402
from factorio_launcher.ui.theme import apply_theme  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    apply_theme(app)
    return app


def png_bytes(w=400, h=225, color="#336699") -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(color))
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def jpg_bytes(w=1600, h=900, color="#aa5522") -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(color))
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "JPG")
    return bytes(buf.data())


@pytest.fixture
def ctx(qapp, tmp_path, fake_install, monkeypatch):
    c = AppContext(tmp_path / "launcher-data")
    c.pm.add_install(fake_install)
    monkeypatch.setattr(c.auth, "load", lambda: None)
    return c


# ---------- modelo: compatibilidade com perfis antigos ----------
def test_old_manifest_without_new_fields_still_loads(ctx, fake_install):
    p = ctx.pm.create_profile("Antigo", fake_install)
    mf = ctx.pm.profile_root(p.id) / "manifest.json"
    data = json.loads(mf.read_text(encoding="utf-8"))
    for k in ("banner", "favorite", "play_seconds"):
        data["profile"].pop(k)
    mf.write_text(json.dumps(data), encoding="utf-8")
    ctx.pm.assets  # noqa: B018
    q = ctx.pm.get_profile(p.id)
    assert (q.banner, q.favorite, q.play_seconds) == ("", False, 0) and q.name == "Antigo"


# ---------- assets ----------
def test_catalog_has_only_official_https_hosts_and_unique_ids():
    ids = [i.id for i in A.OFFICIAL]
    assert len(ids) == len(set(ids)) and len(ids) >= 40
    for i in A.OFFICIAL:
        assert i.url.startswith(("https://cdn.factorio.com/", "https://factorio.com/")) and i.page.startswith("https://factorio.com/")


def make_assets(tmp_path, handler):
    http = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    return A.AssetService(tmp_path / "d", http)


def test_download_optimizes_and_writes_manifest_without_bundling(qapp, tmp_path):
    seen = []

    def h(req):
        seen.append(str(req.url))
        return httpx.Response(200, content=jpg_bytes(2400, 1350), headers={"content-type": "image/jpeg"})

    svc = make_assets(tmp_path, h)
    n, errs = svc.download_official(only=["screenshot-1", "sa-aquilo"], delay=0)
    assert n == 2 and not errs
    p = svc.image_path("screenshot-1")
    img = QImage(str(p))
    assert img.width() == A.BANNER_W and svc.thumb_path("screenshot-1") and QImage(str(svc.thumb_path("screenshot-1"))).width() == A.THUMB_W
    assert seen[0] == "https://cdn.factorio.com/assets/img/screenshots/screenshot-1.jpg"
    man = json.loads((svc.root / "manifest.json").read_text(encoding="utf-8"))
    one = next(i for i in man["images"] if i["id"] == "screenshot-1")
    assert one["url"] == seen[0] and one["source"] == "https://factorio.com/game/screenshots" and one["author"].startswith("Wube")
    assert "redistribuir" in one["license"] and one["bundled_in_launcher"] is False and one["sha256"]
    assert next(i for i in man["images"] if i["id"] == "screenshot-9")["local_path"] is None   # não baixada → sem arquivo inventado
    n2, _ = svc.download_official(only=["screenshot-1"], delay=0)     # já em cache: sem nova requisição
    assert n2 == 0 and len(seen) == 2


def test_download_failures_are_reported_not_fatal(qapp, tmp_path):
    def h(req):
        if "screenshot-2" in str(req.url):
            return httpx.Response(404)
        if "screenshot-3" in str(req.url):
            return httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"})
        if "screenshot-4" in str(req.url):
            return httpx.Response(200, content=b"not really an image", headers={"content-type": "image/jpeg"})
        return httpx.Response(200, content=jpg_bytes(800, 450), headers={"content-type": "image/jpeg"})

    svc = make_assets(tmp_path, h)
    n, errs = svc.download_official(only=["screenshot-1", "screenshot-2", "screenshot-3", "screenshot-4"], delay=0)
    assert n == 1 and len(errs) == 3
    assert not list(svc.shots.glob("*.part")) and svc.image_path("screenshot-2") is None


def test_download_refuses_redirect_and_foreign_hosts(qapp, tmp_path):
    svc = make_assets(tmp_path, lambda r: httpx.Response(302, headers={"location": "https://evil.example/x.jpg"}))
    n, errs = svc.download_official(only=["screenshot-1"], delay=0)
    assert n == 0 and errs
    with pytest.raises(A.AssetError):
        svc._fetch("https://evil.example/x.jpg")
    with pytest.raises(A.AssetError):
        svc._fetch("http://cdn.factorio.com/x.jpg")


def test_default_banner_is_deterministic_per_profile(qapp, tmp_path):
    svc = make_assets(tmp_path, lambda r: httpx.Response(200, content=jpg_bytes(800, 450), headers={"content-type": "image/jpeg"}))
    assert svc.default_for("p1") is None                               # nada baixado → placeholder desenhado
    svc.download_official(only=["screenshot-1", "screenshot-2", "screenshot-3"], delay=0)
    assert svc.default_for("abc") == svc.default_for("abc")
    assert svc.default_for("abc") in {"screenshot-1", "screenshot-2", "screenshot-3"}


# ---------- banners por perfil ----------
def test_banner_import_persist_reset(qapp, ctx, fake_install, tmp_path):
    p = ctx.pm.create_profile("B", fake_install)
    src = tmp_path / "meu banner.png"
    src.write_bytes(png_bytes(2000, 800))
    before = src.read_bytes()
    ctx.pm.import_banner(p, src)
    root = ctx.pm.profile_root(p.id)
    assert ctx.pm.get_profile(p.id).banner == "custom"                  # persistido no manifesto
    f = ctx.pm.banner_file(ctx.pm.get_profile(p.id))
    assert f.parent == root and QImage(str(f)).width() <= A.BANNER_W and src.read_bytes() == before
    # "reinício": nova instância lê o mesmo estado
    ctx2 = AppContext(tmp_path / "launcher-data")
    assert ctx2.pm.banner_file(ctx2.pm.get_profile(p.id)) == f
    ctx.pm.reset_banner(p)
    assert ctx.pm.get_profile(p.id).banner == "" and not list(root.glob("banner.*"))


def test_banner_rejects_bad_files(qapp, ctx, fake_install, tmp_path):
    p = ctx.pm.create_profile("B", fake_install)
    bad = tmp_path / "x.png"
    bad.write_bytes(b"not an image")
    with pytest.raises(ProfileError):
        ctx.pm.import_banner(p, bad)
    with pytest.raises(ProfileError):
        ctx.pm.import_banner(p, tmp_path / "nope.png")
    tiny = tmp_path / "tiny.png"
    tiny.write_bytes(png_bytes(10, 10))
    with pytest.raises(ProfileError):
        ctx.pm.import_banner(p, tiny)
    assert ctx.pm.get_profile(p.id).banner == ""


def test_official_banner_requires_download_and_clone_keeps_banner(qapp, ctx, fake_install, tmp_path):
    p = ctx.pm.create_profile("O", fake_install)
    with pytest.raises(ProfileError):
        ctx.pm.set_official_banner(p, "screenshot-1")
    ctx.pm.assets.shots.mkdir(parents=True)
    (ctx.pm.assets.shots / "screenshot-1.jpg").write_bytes(jpg_bytes(800, 450))
    ctx.pm.set_official_banner(p, "screenshot-1")
    assert ctx.pm.banner_file(ctx.pm.get_profile(p.id)).name == "screenshot-1.jpg"
    src = tmp_path / "c.png"
    src.write_bytes(png_bytes(900, 300))
    ctx.pm.import_banner(p, src)
    d = ctx.pm.duplicate_profile(ctx.pm.get_profile(p.id), "Clone")
    assert d.banner == "custom" and ctx.pm.banner_file(d).parent == ctx.pm.profile_root(d.id)
    ctx.pm.delete_profile(d)
    assert ctx.pm.banner_file(ctx.pm.get_profile(p.id)).is_file()      # o clone não compartilhava o arquivo


def test_missing_custom_file_falls_back_gracefully(qapp, ctx, fake_install):
    p = ctx.pm.create_profile("M", fake_install)
    p.banner = "custom"
    ctx.pm.save_profile(p)
    assert ctx.pm.banner_file(p) is None       # arquivo sumiu: o card usa o banner desenhado, sem erro
    win = MainWindow(ctx)
    win.library.refresh()


# ---------- resumo, mods, saves ----------
def test_summary_is_cached_and_invalidates(ctx, fake_install, mkzip):
    p = ctx.pm.create_profile("S", fake_install)
    assert (ctx.pm.summary(p).mods, ctx.pm.summary(p).saves) == (0, 0)
    first = ctx.pm.summary(p)
    assert ctx.pm.summary(p) is first
    ctx.pm.install_zip(p, mkzip("A", "1.0.0"))
    (ctx.pm.saves_dir(p) / "a.zip").write_bytes(b"x")
    s = ctx.pm.summary(p)
    assert (s.mods, s.saves) == (1, 1)


def test_toggle_respects_dependencies(ctx, fake_install, mkzip):
    p = ctx.pm.create_profile("T", fake_install)
    ctx.pm.install_zip(p, mkzip("lib", "1.0.0", deps=["base"]))
    ctx.pm.install_zip(p, mkzip("app", "1.0.0", deps=["base", "lib >= 1.0.0"]))
    ctx.pm.install_zip(p, mkzip("bad", "1.0.0", deps=["base", "! app"]))
    assert any("app depende" in s for s in ctx.pm.toggle_problems(p, "lib", False))
    assert ctx.pm.toggle_problems(p, "app", False) == []
    assert ctx.pm.toggle_problems(p, "base", False)
    local_mods.set_enabled(ctx.pm.mods_dir(p), "bad", False)
    local_mods.set_enabled(ctx.pm.mods_dir(p), "lib", False)
    assert any("exige lib" in s for s in ctx.pm.toggle_problems(p, "app", True))
    local_mods.set_enabled(ctx.pm.mods_dir(p), "lib", True)
    assert any("incompatível com app" in s for s in ctx.pm.toggle_problems(p, "bad", True))


def test_mod_icon_and_save_preview_cached(ctx, fake_install, tmp_path):
    p = ctx.pm.create_profile("I", fake_install)
    z = tmp_path / "zips" / "Iconic_1.0.0.zip"
    z.parent.mkdir()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("Iconic_1.0.0/info.json", json.dumps({"name": "Iconic", "version": "1.0.0"}))
        zf.writestr("Iconic_1.0.0/thumbnail.png", png_bytes(144, 144))
        zf.writestr("Iconic_1.0.0/../evil/thumbnail.png", b"x")
    with pytest.raises(local_mods.ModError):
        ctx.pm.install_zip(p, z)                                       # entrada insegura bloqueia o ZIP inteiro
    z2 = tmp_path / "zips" / "Iconic2_1.0.0.zip"
    with zipfile.ZipFile(z2, "w") as zf:
        zf.writestr("Iconic2_1.0.0/info.json", json.dumps({"name": "Iconic2", "version": "1.0.0"}))
        zf.writestr("Iconic2_1.0.0/thumbnail.png", png_bytes(144, 144))
    ctx.pm.install_zip(p, z2)
    mod = ctx.pm.scan_mods(p)[0]
    icon = ctx.pm.mod_icon(p, mod)
    assert icon and icon.is_file() and ctx.pm.mod_icon(p, mod) == icon
    save = ctx.pm.saves_dir(p) / "mundo.zip"
    with zipfile.ZipFile(save, "w") as zf:
        zf.writestr("mundo/level.dat", b"0")
        zf.writestr("mundo/preview.jpg", jpg_bytes(320, 180))
    prev = ctx.pm.save_preview(save)
    assert prev and QImage(str(prev)).width() == 320
    nop = ctx.pm.saves_dir(p) / "sem.zip"
    with zipfile.ZipFile(nop, "w") as zf:
        zf.writestr("sem/level.dat", b"0")
    assert ctx.pm.save_preview(nop) is None and ctx.pm.save_preview(tmp_path / "nao-existe.zip") is None


def test_play_time_accumulates_without_clobbering(ctx, fake_install):
    p = ctx.pm.create_profile("P", fake_install)
    ctx.pm.set_favorite(ctx.pm.get_profile(p.id), True)
    ctx.pm.add_play_time(p.id, 600)
    ctx.pm.add_play_time(p.id, 0)
    ctx.pm.add_play_time("inexistente", 50)
    q = ctx.pm.get_profile(p.id)
    assert q.play_seconds == 600 and q.favorite is True


# ---------- biblioteca (UI) ----------
def _mkprofiles(ctx, fake_install, mkzip):
    a = ctx.pm.create_profile("Krastorio", fake_install, SAVE_EXCLUSIVE)
    b = ctx.pm.create_profile("Vanilla", fake_install, SAVE_SHARED, shared_dir=str(ctx.data_dir / "shared"))
    c = ctx.pm.create_profile("Alpha", fake_install, SAVE_EXCLUSIVE)
    ctx.pm.install_zip(a, mkzip("Krastorio2", "2.0.0"))
    ctx.pm.install_zip(a, mkzip("flib", "0.1.0"))
    ctx.pm.install_zip(c, mkzip("solo", "1.0.0"))
    a.last_played, b.last_played = "2026-10-20T10:00:00", "2026-10-22T10:00:00"
    a.created_at, b.created_at, c.created_at = "2026-01-01T00:00:00", "2026-02-01T00:00:00", "2026-03-01T00:00:00"
    for q in (a, b, c):
        ctx.pm.save_profile(q)
    return a, b, c


def _visible_names(lib):
    return [p.name for p in lib._visible_profiles()]


def test_library_filters_counts_search_sort(qapp, ctx, fake_install, mkzip):
    a, b, c = _mkprofiles(ctx, fake_install, mkzip)
    ctx.pm.set_favorite(ctx.pm.get_profile(b.id), True)
    win = MainWindow(ctx)
    lib = win.library
    lib.refresh()
    counts = {k: ch.text() for k, ch in lib.chips.items()}
    assert "(3)" in counts["all"] and "(1)" in counts["fav"] and "(2)" in counts["mods"] and "(1)" in counts["vanilla"]
    assert _visible_names(lib) == ["Vanilla", "Krastorio", "Alpha"]          # último jogado primeiro; nunca jogado por último
    lib.set_filter("mods")
    assert set(_visible_names(lib)) == {"Krastorio", "Alpha"}
    lib.set_filter("vanilla")
    assert _visible_names(lib) == ["Vanilla"]
    lib.set_filter("fav")
    assert _visible_names(lib) == ["Vanilla"]
    lib.set_filter("all")
    for key, expected in (("name_az", ["Alpha", "Krastorio", "Vanilla"]), ("name_za", ["Vanilla", "Krastorio", "Alpha"]),
                          ("mods", ["Krastorio", "Alpha", "Vanilla"]), ("created", ["Alpha", "Vanilla", "Krastorio"])):
        lib.sort.setCurrentIndex(lib.sort.findData(key))
        assert _visible_names(lib) == expected, key
    lib.search.setText("krastorio2")                       # busca pelo nome de um mod do perfil (metadado real)
    assert _visible_names(lib) == ["Krastorio"]
    lib.search.setText("compartilhado")
    assert _visible_names(lib) == ["Vanilla"]
    lib.search.setText("zzzz")
    lib._apply_view()
    assert _visible_names(lib) == []
    assert not lib.empty.isHidden() and "Nenhum resultado" in lib.empty_title.text()
    # filtro/ordenação persistem entre execuções
    assert ctx.settings()["library_filter"] == "all" and ctx.settings()["library_sort"] == "created"


def test_library_empty_states(qapp, ctx):
    win = MainWindow(ctx)
    lib = win.library
    lib.refresh()
    assert not lib.empty.isHidden() and "Nenhum perfil" in lib.empty_title.text() and not lib.empty_btn.isHidden()
    ctx2 = AppContext(ctx.data_dir / "novo")
    ctx2.auth.load = lambda: None
    w2 = MainWindow(ctx2)
    w2.library.refresh()
    assert not w2.library.banner.isHidden()                  # sem instalação do Factorio: aviso real


def test_selection_panel_and_persistence(qapp, ctx, fake_install, mkzip):
    a, b, c = _mkprofiles(ctx, fake_install, mkzip)
    win = MainWindow(ctx)
    win.resize(1500, 900)
    win.show()
    lib = win.library
    lib.refresh()
    assert not lib._panel_open
    lib.select(a.id)
    assert lib._panel_open and lib.panel.pid == a.id and lib._cards[a.id]._selected and not lib._cards[b.id]._selected
    assert lib.panel.hero.name.text() == "Krastorio" and lib.panel.play_btn.isEnabled()
    lib.select(b.id)
    assert lib.panel.pid == b.id and not lib._cards[a.id]._selected
    lib.refresh()                                            # atualização normal não perde a seleção
    assert lib._selected == b.id and lib.panel.pid == b.id
    assert ctx.settings()["library_selected"] == b.id
    lib.close_panel(animate=False)
    assert not lib._panel_open and lib._selected is None and ctx.settings()["library_selected"] is None
    lib.select(a.id)
    win2 = MainWindow(ctx)                                   # reinício: restaura a seleção
    win2.resize(1500, 900)
    win2.show()
    win2.library.refresh()
    assert win2.library._selected == a.id and win2.library._panel_open


def test_panel_docked_vs_drawer(qapp, ctx, fake_install, mkzip):
    a, *_ = _mkprofiles(ctx, fake_install, mkzip)
    win = MainWindow(ctx)
    win.resize(1500, 900)
    win.show()
    lib = win.library
    lib.refresh()
    lib.select(a.id)
    QtWidgets.QApplication.processEvents()
    lib._slide.stop()
    lib._relayout()
    assert lib.docked and lib.content.width() == lib.width() - lib.panel.width() > 0
    win.resize(900, 700)
    QtWidgets.QApplication.processEvents()
    lib._relayout()
    assert not lib.docked and lib.content.width() == lib.width()           # gaveta: o conteúdo mantém a largura toda
    assert lib.panel.geometry().right() >= lib.width() - 2 and lib.panel.width() <= lib.width()
    assert lib._bar_narrow is True


def test_cards_reflow_with_width(qapp, ctx, fake_install, mkzip):
    for i in range(7):
        ctx.pm.create_profile(f"P{i}", fake_install)
    win = MainWindow(ctx)
    win.resize(1900, 900)
    win.show()
    lib = win.library
    lib.refresh()
    QtWidgets.QApplication.processEvents()
    wide = lib._columns
    win.resize(1000, 900)
    QtWidgets.QApplication.processEvents()
    lib._relayout()
    assert wide > lib._columns >= 1


def test_card_states_and_play_button(qapp, ctx, fake_install, mkzip):
    a, b, c = _mkprofiles(ctx, fake_install, mkzip)
    broken = ctx.pm.create_profile("Quebrado", fake_install)
    broken.install_id = "sumiu"
    ctx.pm.save_profile(broken)
    win = MainWindow(ctx)
    lib = win.library
    lib.refresh()
    assert lib._cards[a.id].play_btn.isEnabled() and not lib._cards[broken.id].play_btn.isEnabled()
    assert "ausente" in lib._cards[broken.id].sub.text()
    assert "21" not in lib._cards[a.id].s_mods.value.text() and lib._cards[a.id].s_mods.value.text() == "2"
    assert lib._cards[a.id].s_time.value.text() == "—"       # tempo jogado não registrado: nada inventado
    ctx.pm.add_play_time(a.id, 3700)
    lib.refresh()
    assert lib._cards[a.id].s_time.value.text() == "1h 01min"


def test_play_buttons_use_runner_with_profile_paths_and_load_game(qapp, ctx, fake_install, mkzip, monkeypatch):
    a, *_ = _mkprofiles(ctx, fake_install, mkzip)
    calls = []
    monkeypatch.setattr(ctx.runner, "launch", lambda p, i, m, cfg, extra=None: calls.append((p.id, m, cfg, extra)))
    lib = MainWindow(ctx).library
    lib.refresh()
    lib._play(a.id)
    lib._play_save(a.id, "C:/saves/meu mundo.zip")
    assert calls[0] == (a.id, ctx.pm.mods_dir(a), ctx.pm.config_file(a), None)
    assert calls[1][3] == ["--load-game", "C:/saves/meu mundo.zip"] and calls[1][1] == ctx.pm.mods_dir(a)


def test_panel_toggle_mod_blocked_by_dependency_and_running(qapp, ctx, fake_install, mkzip, monkeypatch):
    p = ctx.pm.create_profile("D", fake_install)
    ctx.pm.install_zip(p, mkzip("lib", "1.0.0", deps=["base"]))
    ctx.pm.install_zip(p, mkzip("app", "1.0.0", deps=["base", "lib"]))
    errors = []
    import factorio_launcher.ui.detail_panel as dp
    monkeypatch.setattr(dp, "error", lambda parent, title, text: errors.append(text))
    panel = dp.DetailPanel(ctx)
    panel.show_profile(p)
    from factorio_launcher.ui.library_widgets import ToggleSwitch
    sw = ToggleSwitch(True)
    panel._toggle_mod("lib", False, sw)                        # app exige lib → bloqueado
    assert errors and "depende" in errors[-1]
    assert local_mods.read_mod_list(ctx.pm.mods_dir(p))["lib"] is True
    sw2 = ToggleSwitch(True)
    panel._toggle_mod("app", False, sw2)                       # livre: desabilita de verdade
    assert local_mods.read_mod_list(ctx.pm.mods_dir(p))["app"] is False
    monkeypatch.setattr(ctx.runner, "is_profile_running", lambda pid: True)
    panel._toggle_mod("app", True, ToggleSwitch(False))
    assert "Feche o Factorio" in errors[-1] and local_mods.read_mod_list(ctx.pm.mods_dir(p))["app"] is False


def test_exclusive_profile_never_lists_other_profiles_saves_or_cloud(qapp, ctx, fake_install, monkeypatch):
    from factorio_launcher.services import steam_cloud
    a = ctx.pm.create_profile("A", fake_install, SAVE_EXCLUSIVE)
    b = ctx.pm.create_profile("B", fake_install, SAVE_EXCLUSIVE)
    (ctx.pm.saves_dir(a) / "so-do-a.zip").write_bytes(b"x")
    monkeypatch.setattr(steam_cloud, "list_cloud_saves", lambda roots=None: [steam_cloud.CloudSave("nuvem.zip", 1, 1700000000, "1", True)])
    import factorio_launcher.ui.detail_panel as dp
    panel = dp.DetailPanel(ctx)
    panel.show_profile(b)
    texts = " ".join(w.text() for w in panel.body.findChildren(QtWidgets.QLabel))
    assert "so-do-a" not in texts and "nuvem" not in texts and "Nenhum save" in texts
    panel.show_profile(a)
    texts = " ".join(w.text() for w in panel.body.findChildren(QtWidgets.QLabel))
    assert "so-do-a" in texts and "nuvem" not in texts
    sh = ctx.pm.create_profile("S", fake_install, SAVE_SHARED, shared_dir=str(ctx.data_dir / "sh"))
    panel.show_profile(sh)
    texts = " ".join(w.text() for w in panel.body.findChildren(QtWidgets.QLabel))
    assert "nuvem" in texts and "só na nuvem" in texts


def test_downloads_badge_counts_active_jobs(qapp, ctx, fake_install):
    from factorio_launcher.services.download_manager import DownloadJob, RUNNING, DONE
    from factorio_launcher.services.portal_client import Release
    p = ctx.pm.create_profile("P", fake_install)
    win = MainWindow(ctx)
    win.show()
    j1 = DownloadJob(Release("a", "1.0.0", "/download/a/x", "a.zip", "0" * 40), p.id, ctx.pm.mods_dir(p))
    j2 = DownloadJob(Release("b", "1.0.0", "/download/b/x", "b.zip", "0" * 40), p.id, ctx.pm.mods_dir(p))
    j1.status, j2.status = RUNNING, DONE
    ctx.downloads.jobs += [j1, j2]
    win._update_badge()
    badge = win._nav["dl"][0].badge
    assert badge.isVisible() and badge.text() == "1"
    j1.status = DONE
    win._update_badge()
    assert not badge.isVisible()


def test_game_exit_records_time_and_ignores_short_sessions(qapp, ctx, fake_install):
    p = ctx.pm.create_profile("G", fake_install)
    win = MainWindow(ctx)
    win.library.on_game_exit(p.id, 3)
    assert ctx.pm.get_profile(p.id).play_seconds == 0
    win.library.on_game_exit(p.id, 125)
    assert ctx.pm.get_profile(p.id).play_seconds == 125


def test_design_tokens_are_the_single_source_of_colors():
    import re
    from factorio_launcher.ui import tokens as T
    root = Path(__file__).resolve().parent.parent / "src" / "factorio_launcher" / "ui"
    for name in ("library_page.py", "library_widgets.py", "detail_panel.py", "banner_dialog.py"):
        text = (root / name).read_text(encoding="utf-8")
        hexes = set(re.findall(r"#[0-9a-fA-F]{6}\b", text))
        # só tolera tons de sobreposição/hover locais (rgba e 2-3 neutros); cores de marca vêm dos tokens
        brand = {T.ORANGE, T.ORANGE_HOVER, T.BLUE, T.GREEN, T.RED, T.CARD, T.SIDEBAR, T.BG, T.BORDER}
        assert not (hexes & {h for h in brand if h in hexes}), (name, hexes & brand)
