"""Fumaça da UI em modo offscreen: navegação e fluxos principais, com diretórios isolados."""
import os

import pytest
from PySide6.QtCore import Qt

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from factorio_launcher.app import AppContext
from factorio_launcher.models.entities import SAVE_EXCLUSIVE
from factorio_launcher.ui.main_window import MainWindow
from factorio_launcher.ui.theme import apply_theme


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    apply_theme(app)
    return app


def test_navigation_and_library_states(qapp, tmp_path, fake_install):
    ctx = AppContext(tmp_path / "launcher-data")
    win = MainWindow(ctx)
    win.show()
    for page in (win.library, win.explore, win.downloads, win.settings):
        win.goto(page)
        assert win.stack.currentWidget() is page
    win.goto(win.library)
    assert not win.library.banner.isHidden()           # sem Factorio: aviso real
    ctx.pm.add_install(fake_install)
    win.library.refresh()
    assert win.library.banner.isHidden() and not win.library.empty.isHidden()


def test_profile_page_install_zip_toggle_and_play_args(qapp, tmp_path, fake_install, mkzip, monkeypatch):
    ctx = AppContext(tmp_path / "launcher-data")
    ctx.pm.add_install(fake_install)
    a = ctx.pm.create_profile("Alpha", fake_install, SAVE_EXCLUSIVE)
    b = ctx.pm.create_profile("Beta", fake_install, SAVE_EXCLUSIVE)
    win = MainWindow(ctx)
    win.library.refresh()
    assert len(win.library._cards) == 2
    win.open_profile(a.id)
    page = win.profile_page
    ctx.pm.install_zip(a, mkzip("OnlyInAlpha", "1.0.0"))
    page.refresh()
    assert page.mod_table.rowCount() == 1
    page.mod_table.item(0, 0).setCheckState(QtWidgets.QApplication.instance() and __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.Unchecked)
    assert ctx.pm.scan_mods(a)[0].enabled is False
    assert ctx.pm.scan_mods(b) == []
    # JOGAR chama o runner com os caminhos do perfil
    calls = {}
    monkeypatch.setattr(ctx.runner, "launch", lambda p, i, m, c, extra=None: calls.update(p=p.name, m=m, c=c))
    page.on_play()
    assert calls["p"] == "Alpha" and calls["m"] == ctx.pm.mods_dir(a) and calls["c"] == ctx.pm.config_file(a)


def test_downloads_page_shows_auth_state(qapp, tmp_path, fake_install):
    from factorio_launcher.services.download_manager import AUTH, DownloadJob
    from factorio_launcher.services.portal_client import Release
    ctx = AppContext(tmp_path / "launcher-data")
    ctx.pm.add_install(fake_install)
    p = ctx.pm.create_profile("P", fake_install)
    win = MainWindow(ctx)
    job = DownloadJob(Release("M", "1.0.0", "/download/M/x", "M.zip", "0" * 40), p.id, ctx.pm.mods_dir(p))
    job.status, job.error = AUTH, "Download requer autenticação"
    win.downloads.on_job(job)
    assert win.downloads.table.item(0, 2).text() == AUTH


def test_explore_page_filters_pagination_and_detail(qapp, tmp_path, fake_install, monkeypatch):
    from factorio_launcher.services import portal_client as pc
    ctx = AppContext(tmp_path / "launcher-data")
    ctx.pm.add_install(fake_install)
    p = ctx.pm.create_profile("P", fake_install)
    cat = [{"name": f"mod{i}", "title": f"Mod {i}", "owner": "o", "summary": "s", "downloads": i, "category": "utilities" if i % 2 else "content",
            "version": "1.0.0", "fv": "2.0", "score": 0, "at": "2025-01-01T00:00:00Z"} for i in range(45)]
    ctx.portal._catalog = cat
    monkeypatch.setattr(ctx.auth, "load", lambda: None)           # modo local (sem login): nunca usa a rede
    monkeypatch.setattr(ctx.portal, "catalog_age", lambda: 10.0)
    monkeypatch.setattr(ctx.portal, "thumbnail", lambda n: None)
    win = MainWindow(ctx)
    ex = win.explore
    ex.refresh()
    assert ex.list.count() == 20 and "45" in ex.count_lbl.text()
    ex._goto(3)
    assert ex.list.count() == 5
    ex._cat_checks["utilities"].setChecked(True)
    assert len(ex._matches) == 22 and ex._page == 1
    assert "22" in ex._cat_checks["utilities"].text()
    ex.query.setText("mod7")
    ex._filters_changed()
    assert [m["name"] for m in ex._matches] == ["mod7"]
    ex._name = "mod7"
    rel = {"version": "1.0.0", "download_url": "/download/mod7/x", "file_name": "m.zip", "sha1": "0" * 40,
           "info_json": {"factorio_version": "2.0", "dependencies": ["base >= 2.0", "? opt", "! bad", "dep >= 1.0.0"]}}
    ex._details("mod7", {"owner": "bob", "homepage": "https://example.com", "github_path": "bob/mod7", "changelog": "x",
                         "description": "Descrição <b>x</b>", "releases": [rel]})
    assert "bob" in ex._cells["Autor"].text() and "https://github.com/bob/mod7" in ex._cells["Código-fonte"].text()
    assert "opcional" in ex._cells["Dependências"].text() and "dep" in ex._cells["Dependências"].text()
    assert "&lt;b&gt;" in ex.d_desc.text()  # HTML do Portal é escapado
    assert ex.install_btn.isEnabled() and ex.changelog_btn.isEnabled()


def test_saves_tab_shows_steam_cloud_only_in_shared_mode(qapp, tmp_path, fake_install, monkeypatch):
    from factorio_launcher.models.entities import SAVE_SHARED
    from factorio_launcher.services import steam_cloud
    ctx = AppContext(tmp_path / "launcher-data")
    ctx.pm.add_install(fake_install)
    sh = ctx.pm.create_profile("Sh", fake_install, SAVE_SHARED, shared_dir=str(tmp_path / "shared"))
    ex = ctx.pm.create_profile("Ex", fake_install, SAVE_EXCLUSIVE)
    (tmp_path / "shared" / "saves").mkdir(parents=True)
    (tmp_path / "shared" / "saves" / "local.zip").write_bytes(b"x")
    monkeypatch.setattr(steam_cloud, "list_cloud_saves", lambda roots=None: [
        steam_cloud.CloudSave("local.zip", 1, 1700000000, "1", True), steam_cloud.CloudSave("nuvem.zip", 5, 1700000001, "1", True)])
    win = MainWindow(ctx)
    win.open_profile(sh.id)
    items = [win.profile_page.saves_list.item(i).text() for i in range(win.profile_page.saves_list.count())]
    assert any("nuvem.zip" in t and "só na nuvem" in t for t in items)
    assert any("local.zip" in t and "também na pasta local" in t for t in items)
    win.open_profile(ex.id)
    assert not any("☁" in win.profile_page.saves_list.item(i).text() for i in range(win.profile_page.saves_list.count()))


# ---------- busca por tags / comandos $ ----------
def _pump(cond, timeout=5.0):
    import time
    from PySide6.QtCore import QThreadPool
    t = time.time()
    while time.time() - t < timeout:
        QtWidgets.QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    QThreadPool.globalInstance().waitForDone(1000)
    QtWidgets.QApplication.processEvents()
    return cond()


def _entry(name, tags):
    return {"name": name, "title": name, "owner": "o", "summary": "s", "downloads": 1, "category": "utilities",
            "version": "1.0.0", "fv": "2.0", "fvs": ["2.0"], "score": 0, "at": "2025-01-01T00:00:00", "tags": tags, "thumb": ""}


@pytest.fixture
def online(qapp, tmp_path, fake_install, monkeypatch):
    ctx = AppContext(tmp_path / "launcher-data")
    ctx.pm.add_install(fake_install)
    ctx.pm.create_profile("P", fake_install)
    monkeypatch.setattr(ctx.auth, "load", lambda: ("bob", "tok"))
    monkeypatch.setattr(ctx.portal, "thumbnail", lambda n, rel=None: None)
    monkeypatch.setattr(ctx.portal, "tag_counts", lambda *a, **k: {"trains": 523, "combat": 1171})
    calls = {"page": [], "all": []}

    def search_api(creds, page=1, page_size=20, **kw):
        calls["page"].append({"creds": creds, "page": page, "page_size": page_size, **kw})
        return [_entry(f"m{page}_{i}", ["trains"]) for i in range(3)], 523

    def search_api_all(creds, **kw):
        calls["all"].append(kw)
        return [_entry("both", ["trains", "logistics"])]

    monkeypatch.setattr(ctx.portal, "search_api", search_api)
    monkeypatch.setattr(ctx.portal, "search_api_all", search_api_all)
    win = MainWindow(ctx)
    return ctx, win.explore, calls


def test_dollar_commands_map_to_api_filters(online):
    ctx, ex, calls = online
    ex.refresh()
    assert _pump(lambda: calls["page"])                      # busca inicial sem filtros
    assert calls["page"][0]["tags"] == [] and calls["page"][0]["exclude_tags"] == []
    calls["page"].clear()

    ex.query.setText("cargo $trem -$combate")                # aliases → ids oficiais
    ex._trigger(True)
    assert _pump(lambda: calls["page"])
    c = calls["page"][-1]
    assert c["query"] == "cargo" and c["tags"] == ["trains"] and c["exclude_tags"] == ["combat"]
    assert c["creds"] == ("bob", "tok") and c["version"] == "2.0.77" and c["show_deprecated"] is False
    assert ex._tag_rows["trains"][0].isChecked() and ex._tag_rows["combat"][1].isChecked()
    assert _pump(lambda: ex.list.count() == 3) and "523" in ex.count_lbl.text()
    assert "com $trains" in ex.status.text() and "sem $combat" in ex.status.text()


def test_multiple_tags_use_all_mode(online):
    ctx, ex, calls = online
    ex.refresh()
    ex.query.setText("$trains $logistics")
    ex._trigger(True)
    assert _pump(lambda: calls["all"])
    assert calls["all"][-1]["tags"] == ["trains", "logistics"]
    assert _pump(lambda: ex.list.count() == 1) and "(todas)" in ex.status.text()


def test_server_pagination_requests_next_page(online):
    ctx, ex, calls = online
    ex.refresh()
    assert _pump(lambda: ex.list.count() == 3)
    ex._goto(5)
    assert _pump(lambda: calls["page"][-1]["page"] == 5)
    assert _pump(lambda: ex._items and ex._items[0]["name"].startswith("m5_"))


def test_unknown_tag_warns_and_is_not_sent(online):
    ctx, ex, calls = online
    ex.refresh()
    calls["page"].clear()
    ex.query.setText("$trains $naoexiste")
    ex._trigger(True)
    assert _pump(lambda: calls["page"])
    assert calls["page"][-1]["tags"] == ["trains"] and "naoexiste" in ex.status.text()


def test_sidebar_clicks_rewrite_command_text(online):
    ctx, ex, calls = online
    ex.refresh()
    ex.query.setText("fast belt")
    ex._tag_rows["trains"][0].setChecked(True)
    assert ex.query.text() == "fast belt $trains "
    ex._tag_rows["combat"][1].setChecked(True)
    assert ex.query.text() == "fast belt $trains -$combat "
    ex._tag_rows["trains"][1].setChecked(True)                # incluir → excluir move o token
    assert not ex._tag_rows["trains"][0].isChecked()
    assert ex.query.text().split()[:2] == ["fast", "belt"] and set(ex.query.text().split()[2:]) == {"-$trains", "-$combat"}
    assert _pump(lambda: set(calls["page"][-1]["exclude_tags"]) == {"combat", "trains"})


def test_autocomplete_popup_and_accept(online):
    ctx, ex, calls = online
    ex.show()
    ex.query.setText("cargo $tr")
    ex.query.setCursorPosition(9)
    ex._update_popup()
    ids = [ex.popup.item(i).data(Qt.UserRole) for i in range(ex.popup.count())]
    assert ex.popup.isVisible() and "trains" in ids and "transportation" in ids
    ex._accept_suggestion("trains")
    assert ex.query.text() == "cargo $trains " and not ex.popup.isVisible()
    ex.query.setText("-$co")
    ex.query.setCursorPosition(4)
    ex._update_popup()
    ex._accept_suggestion("combat")
    assert ex.query.text() == "-$combat "
    ex.query.setText("plain text")
    ex.query.setCursorPosition(10)
    ex._update_popup()
    assert not ex.popup.isVisible()


def test_without_credentials_tags_fall_back_to_local_text_search(qapp, tmp_path, fake_install, monkeypatch):
    ctx = AppContext(tmp_path / "launcher-data")
    ctx.pm.add_install(fake_install)
    ctx.pm.create_profile("P", fake_install)
    monkeypatch.setattr(ctx.auth, "load", lambda: None)
    ctx.portal._catalog = [{"name": "cargo1", "title": "Cargo 1", "owner": "o", "summary": "", "downloads": 1,
                            "category": "utilities", "version": "1.0.0", "fv": "2.0", "score": 0, "at": ""}]
    monkeypatch.setattr(ctx.portal, "catalog_age", lambda: 10.0)
    monkeypatch.setattr(ctx.portal, "thumbnail", lambda n, rel=None: None)
    monkeypatch.setattr(ctx.portal, "search_api", lambda *a, **k: pytest.fail("não deve chamar a API sem login"))
    ex = MainWindow(ctx).explore
    ex.refresh()
    assert not ex.tag_note.isHidden() and not ex._tag_rows["trains"][0].isEnabled()
    ex.query.setText("cargo $trains")
    ex._trigger(True)
    assert [m["name"] for m in ex._items] == ["cargo1"] and "login" in ex.status.text()


def test_offline_falls_back_to_catalog(online, monkeypatch):
    from factorio_launcher.services.portal_client import PortalOffline
    ctx, ex, calls = online
    ctx.portal._catalog = [{"name": "loc", "title": "Local", "owner": "o", "summary": "", "downloads": 1,
                            "category": "utilities", "version": "1.0.0", "fv": "2.0", "score": 0, "at": ""}]
    monkeypatch.setattr(ctx.portal, "catalog_age", lambda: 10.0)

    def boom(*a, **k):
        raise PortalOffline("x")

    monkeypatch.setattr(ctx.portal, "search_api", boom)
    ex.refresh()
    assert _pump(lambda: [m["name"] for m in ex._items] == ["loc"]) and "Sem conexão" in ex.status.text()
