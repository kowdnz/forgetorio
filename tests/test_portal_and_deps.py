import hashlib
import json
import threading

import httpx
import pytest

from factorio_launcher.logsetup import redact
from factorio_launcher.models.entities import ModInfo
from factorio_launcher.models.versions import parse_dependency, parse_version
from factorio_launcher.services import dependency_resolver as dr
from factorio_launcher.services import download_manager as dm
from factorio_launcher.services import portal_client as pc
from factorio_launcher.services.auth_store import AuthStore, read_player_data_credentials
from conftest import make_mod_zip


# ---------- dependências: sintaxe ----------
@pytest.mark.parametrize("text,kind,name,op,ver", [
    ("base >= 2.0", "required", "base", ">=", (2, 0, 0)),
    ("? some-mod", "optional", "some-mod", None, None),
    ("(?) hidden", "hidden_optional", "hidden", None, None),
    ("! bad_mod", "incompatible", "bad_mod", None, None),
    ("~ late >= 1.2.3", "no_order", "late", ">=", (1, 2, 3)),
    ("plain", "required", "plain", None, None),
    ("Mod With Space = 1.0.0", "required", "Mod With Space", "=", (1, 0, 0)),
])
def test_dep_parser(text, kind, name, op, ver):
    d = parse_dependency(text)
    assert (d.kind, d.name, d.op, d.version) == (kind, name, op, ver)


def test_dep_accepts():
    d = parse_dependency("x >= 1.2.0")
    assert d.accepts((1, 2, 0)) and d.accepts((2, 0, 0)) and not d.accepts((1, 1, 9))


# ---------- compat ----------
def test_game_compat():
    assert pc.game_compat("2.0", "2.0.77") == "ok"
    assert pc.game_compat("2.0", "2.1.23") == "maybe"
    assert pc.game_compat("1.1", "2.0.77") == "no"
    assert pc.game_compat("2.1", "2.0.77") == "no"


# ---------- resolver ----------
def R(name, ver, deps=None, fv="2.0"):
    return pc.Release(name, ver, f"/download/{name}/x", f"{name}_{ver}.zip", "0" * 40, fv, deps if deps is not None else ["base"])


def fetch_factory(table):
    return lambda name: table[name]


def test_transitive_resolution_picks_latest_compatible():
    table = {"B": [R("B", "1.0.0"), R("B", "1.5.0", ["base", "C >= 1.0.0"]), R("B", "3.0.0", ["base"], "1.1")],
             "C": [R("C", "1.0.0"), R("C", "2.0.0")]}
    plan = dr.resolve_install(R("A", "1.0.0", ["base >= 2.0", "B >= 1.0.0", "? Opt"]), [], "2.0.77", [], fetch_factory(table))
    assert plan.ok, plan.report()
    assert sorted((r.name, r.version) for r in plan.to_install) == [("A", "1.0.0"), ("B", "1.5.0"), ("C", "2.0.0")]
    assert plan.optional == ["Opt"]


def test_unsatisfiable_version_is_issue_and_no_partial():
    table = {"B": [R("B", "1.0.0")]}
    plan = dr.resolve_install(R("A", "1.0.0", ["B >= 2.0.0"]), [], "2.0.77", [], fetch_factory(table))
    assert not plan.ok and any("Nenhuma versão de B" in i for i in plan.issues)


def test_incompatible_with_installed():
    inst = [ModInfo("X", "1.0.0", dependencies=["base"], enabled=True)]
    plan = dr.resolve_install(R("A", "1.0.0", ["base", "! X"]), inst, "2.0.77", [], fetch_factory({}))
    assert not plan.ok and any("incompatível com X" in i for i in plan.issues)


def test_installed_declares_incompatibility():
    inst = [ModInfo("X", "1.0.0", dependencies=["base", "! A"], enabled=True)]
    plan = dr.resolve_install(R("A", "1.0.0"), inst, "2.0.77", [], fetch_factory({}))
    assert not plan.ok


def test_dlc_missing_and_present():
    rel = R("A", "1.0.0", ["base", "space-age"])
    assert not dr.resolve_install(rel, [], "2.0.77", [], fetch_factory({})).ok
    assert dr.resolve_install(rel, [], "2.0.77", ["space-age"], fetch_factory({})).ok


def test_game_version_mismatch_and_base_constraint():
    assert not dr.resolve_install(R("A", "1.0.0", fv="1.1"), [], "2.0.77", [], fetch_factory({})).ok
    assert not dr.resolve_install(R("A", "1.0.0", ["base >= 2.1"]), [], "2.0.77", [], fetch_factory({})).ok


def test_pinned_blocks_update():
    inst = [ModInfo("B", "1.0.0", dependencies=["base"])]
    table = {"B": [R("B", "1.0.0"), R("B", "2.0.0")]}
    plan = dr.resolve_install(R("A", "1.0.0", ["B >= 2.0.0"]), inst, "2.0.77", [], fetch_factory(table), pins={"B": "1.0.0"})
    assert not plan.ok and any("fixado" in i for i in plan.issues)


def test_portal_failure_is_reported_not_raised():
    def boom(name):
        raise pc.PortalOffline("sem rede")

    plan = dr.resolve_install(R("A", "1.0.0", ["B"]), [], "2.0.77", [], boom)
    assert not plan.ok and "sem rede" in plan.issues[0]


def test_check_profile_diagnostics():
    mods = [ModInfo("A", "1.0.0", dependencies=["base", "B >= 2.0.0", "! C", "space-age"], factorio_version="1.1"),
            ModInfo("B", "1.0.0", dependencies=["base"], factorio_version="2.0"),
            ModInfo("C", "1.0.0", dependencies=["base"], factorio_version="2.0")]
    text = "\n".join(dr.check_profile(mods, "2.0.77", []))
    assert "B >= 2.0.0" in text.replace("exige B ", "B ") or "exige B" in text
    assert "incompatível com C" in text and "DLC space-age" in text and "feito para Factorio 1.1" in text


# ---------- cliente HTTP (mock) ----------
def make_client(handler, tmp_path):
    http = httpx.Client(transport=httpx.MockTransport(handler), headers={"User-Agent": "t"}, follow_redirects=False)
    return pc.PortalClient(tmp_path / "cache", http, min_interval=0, retries=2, backoff=0)


def test_offline_raises_portal_offline(tmp_path):
    def h(req):
        raise httpx.ConnectError("down")

    with pytest.raises(pc.PortalOffline):
        make_client(h, tmp_path).list_page()


def test_full_cached_when_offline(tmp_path):
    state = {"online": True}

    def h(req):
        if not state["online"]:
            raise httpx.ConnectError("down")
        return httpx.Response(200, json={"name": "M", "releases": [{"version": "1.0.0", "download_url": "/download/M/1", "file_name": "M_1.0.0.zip", "sha1": "a" * 40, "info_json": {"factorio_version": "2.0"}}]})

    c = make_client(h, tmp_path)
    assert c.releases("M")[0].version == "1.0.0"
    state["online"] = False
    c2 = make_client(h, tmp_path)
    assert c2.releases("M")[0].version == "1.0.0"


def test_retry_then_success_and_404(tmp_path):
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"results": [], "pagination": {"page_count": 3}})

    assert make_client(h, tmp_path).list_page()[1] == 3
    with pytest.raises(pc.PortalError, match="não encontrado"):
        make_client(lambda r: httpx.Response(404), tmp_path).get_full("Nope")


def test_invalid_mod_name_rejected(tmp_path):
    with pytest.raises(pc.PortalError):
        make_client(lambda r: httpx.Response(200, json={}), tmp_path).get_full("../../etc")


def test_catalog_refresh_and_search(tmp_path):
    results = [{"name": "Krastorio2", "title": "Krastorio 2", "owner": "Krastor", "summary": "big overhaul", "downloads_count": 900, "category": "overhaul", "latest_release": {"version": "2.0.0", "info_json": {"factorio_version": "2.0"}}},
               {"name": "Old", "title": "Old mod", "owner": "x", "summary": "krastorio addon", "downloads_count": 5, "category": "content", "latest_release": {"version": "0.1.0", "info_json": {"factorio_version": "0.17"}}}]
    c = make_client(lambda r: httpx.Response(200, json={"results": results}), tmp_path)
    assert c.refresh_catalog() == 2
    assert [m["name"] for m in c.search("krastorio")] == ["Krastorio2", "Old"]
    assert [m["name"] for m in c.search("krastorio", game_version="2.0.77")] == ["Krastorio2"]


# ---------- download ----------
def build_release(tmp_path, name="M", version="1.0.0", **zipkw):
    z = make_mod_zip(tmp_path / "src.zip", name, version, **zipkw)
    data = z.read_bytes()
    return R(name, version, ["base"]).__class__(name, version, f"/download/{name}/abc", f"{name}_{version}.zip",
                                                 hashlib.sha1(data).hexdigest(), "2.0", ["base"]), data


def test_download_ok_with_redirect_and_no_creds_leak(tmp_path):
    rel, data = build_release(tmp_path)
    seen = []

    def h(req):
        seen.append(req)
        if req.url.host == "mods.factorio.com":
            return httpx.Response(302, headers={"location": "https://dl-mod.factorio.com/files/M.zip?sig=1"})
        return httpx.Response(200, content=data, headers={"content-length": str(len(data))})

    c = make_client(h, tmp_path)
    out = c.download(rel, ("user", "SECRET"))
    assert out.is_file() and not list(out.parent.glob("*.part"))
    assert "SECRET" in str(seen[0].url) and all("SECRET" not in str(r.url) for r in seen[1:])


def test_download_requires_auth(tmp_path):
    rel, _ = build_release(tmp_path)
    with pytest.raises(pc.AuthRequired):
        make_client(lambda r: httpx.Response(200), tmp_path).download(rel, None)
    with pytest.raises(pc.AuthRequired):
        make_client(lambda r: httpx.Response(403), tmp_path).download(rel, ("u", "t"))


def test_download_bad_sha1_discarded(tmp_path):
    rel, data = build_release(tmp_path)
    rel.sha1 = "f" * 40
    c = make_client(lambda r: httpx.Response(200, content=data), tmp_path)
    with pytest.raises(pc.PortalError, match="SHA-1"):
        c.download(rel, ("u", "t"))
    assert not c.mod_cache_path(rel).exists() and not list(c.mod_cache_path(rel).parent.glob("*.part"))


def test_download_truncated(tmp_path):
    rel, data = build_release(tmp_path)

    def h(req):
        return httpx.Response(200, content=data[: len(data) // 2], headers={"content-length": str(len(data))})

    with pytest.raises(Exception):
        make_client(h, tmp_path).download(rel, ("u", "t"))
    assert not list((tmp_path / "cache").rglob("*.part"))


def test_download_redirect_to_foreign_host_blocked(tmp_path):
    rel, data = build_release(tmp_path)
    seen = []

    def h(req):
        seen.append(str(req.url))
        return httpx.Response(302, headers={"location": "https://evil.example.com/x.zip"})

    with pytest.raises(pc.PortalError, match="host não autorizado"):
        make_client(h, tmp_path).download(rel, ("u", "SECRET"))
    assert all("evil" not in s for s in seen)


def test_download_wrong_mod_inside_zip(tmp_path):
    rel, data = build_release(tmp_path)
    rel.name = "Other"
    with pytest.raises(pc.PortalError, match="não corresponde"):
        make_client(lambda r: httpx.Response(200, content=data), tmp_path).download(rel, ("u", "t"))


def test_download_cancel(tmp_path):
    rel, data = build_release(tmp_path)
    ev = threading.Event()
    ev.set()
    with pytest.raises(pc.Cancelled):
        make_client(lambda r: httpx.Response(200, content=data), tmp_path).download(rel, ("u", "t"), cancel=ev)
    assert not list((tmp_path / "cache").rglob("*.part"))


def test_download_manager_installs_in_correct_profile_only(pm, fake_install, tmp_path):
    a, b = pm.create_profile("A", fake_install), pm.create_profile("B", fake_install)
    rel, data = build_release(tmp_path)
    c = make_client(lambda r: httpx.Response(200, content=data), tmp_path)
    mgr = dm.DownloadManager(c, lambda: ("u", "t"), synchronous=True)
    job = mgr.enqueue(rel, a.id, pm.mods_dir(a))
    assert job.status == dm.DONE
    assert [m.name for m in pm.scan_mods(a)] == ["M"] and pm.scan_mods(b) == []


def test_download_manager_auth_state_and_retry(pm, fake_install, tmp_path):
    a = pm.create_profile("A", fake_install)
    rel, data = build_release(tmp_path)
    creds = {"v": None}
    c = make_client(lambda r: httpx.Response(200, content=data), tmp_path)
    mgr = dm.DownloadManager(c, lambda: creds["v"], synchronous=True)
    job = mgr.enqueue(rel, a.id, pm.mods_dir(a))
    assert job.status == dm.AUTH and pm.scan_mods(a) == []
    creds["v"] = ("u", "t")
    mgr.retry(job)
    assert job.status == dm.DONE


# ---------- segurança de credenciais ----------
def test_redaction():
    assert "SECRET" not in redact("GET https://x/download/a?username=bob&token=SECRET&z=1")
    assert "SECRET" not in redact('{"service-token": "SECRET"}')
    assert "SECRET" not in pc.redact_url("https://x?token=SECRET&username=bob")


class FakeKeyring:
    def __init__(self):
        self.d = {}

    def set_password(self, s, u, p):
        self.d[(s, u)] = p

    def get_password(self, s, u):
        return self.d.get((s, u))

    def delete_password(self, s, u):
        self.d.pop((s, u), None)


def test_auth_store_roundtrip_and_no_plaintext(tmp_path):
    kr = FakeKeyring()
    a = AuthStore(kr)
    a.save("bob", "TOK")
    assert AuthStore(kr).load() == ("bob", "TOK")
    a.clear()
    assert AuthStore(kr).load() is None
    assert not any("TOK" in p.read_text(errors="ignore") for p in tmp_path.rglob("*") if p.is_file())


def test_player_data_import(tmp_path):
    f = tmp_path / "player-data.json"
    f.write_text(json.dumps({"service-username": "bob", "service-token": "T"}), encoding="utf-8")
    assert read_player_data_credentials(f) == ("bob", "T")
    f.write_text("{}")
    assert read_player_data_credentials(f) is None
    assert read_player_data_credentials(tmp_path / "x.json") is None


def test_invalid_dependency_syntax_is_warning_not_crash():
    plan = dr.resolve_install(R("A", "1.0.0", ["base", "+ Weird"]), [], "2.0.77", [], fetch_factory({}))
    assert plan.ok and any("sintaxe inválida" in w for w in plan.warnings)


def test_thumbnail_download_and_validation(tmp_path):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 20

    def h(req):
        if req.url.host == "assets-mod.factorio.com":
            return httpx.Response(200, content=png)
        return httpx.Response(200, json={"name": "M", "thumbnail": "/assets/abc123.thumb.png", "releases": []})

    c = make_client(h, tmp_path)
    p = c.thumbnail("M")
    assert p.read_bytes() == png and c.thumbnail("M") == p

    def evil(req):
        return httpx.Response(200, json={"name": "M", "thumbnail": "https://evil.example/x.png", "releases": []})

    assert make_client(evil, tmp_path / "b").thumbnail("M") is None


def test_catalog_sorts(tmp_path):
    res = [{"name": "a", "title": "A", "owner": "o", "summary": "", "downloads_count": 1, "category": "c", "latest_release": {"version": "1.0.0", "released_at": "2024-01-01", "info_json": {"factorio_version": "2.0"}}},
           {"name": "b", "title": "B", "owner": "o", "summary": "", "downloads_count": 9, "category": "c", "latest_release": {"version": "1.0.0", "released_at": "2025-01-01", "info_json": {"factorio_version": "2.0"}}}]
    c = make_client(lambda r: httpx.Response(200, json={"results": res}), tmp_path)
    c.refresh_catalog()
    assert [m["name"] for m in c.search(sort="updated")] == ["b", "a"]
    assert [m["name"] for m in c.search(sort="name")] == ["a", "b"]
    assert [m["name"] for m in c.search(sort="downloads")] == ["b", "a"]
