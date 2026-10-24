import json
import logging

import httpx
import pytest

from factorio_launcher.services import portal_client as pc
from factorio_launcher.services import tags as T

OFFICIAL = {"planets", "transportation", "logistics", "trains", "combat", "armor", "character", "enemies", "environment",
            "mining", "fluids", "logistic-network", "circuit-network", "manufacturing", "power", "storage", "blueprints",
            "cheats"}


def test_official_ids_are_the_18_validated_against_the_server():
    assert {t.id for t in T.TAGS} == OFFICIAL and len(T.TAGS) == 18


@pytest.mark.parametrize("raw,expected", [
    ("trains", "trains"), ("TRAINS", "trains"), ("trem", "trains"), ("trens", "trains"), ("train", "trains"),
    ("logistica", "logistics"), ("Logística", "logistics"), ("rede-logistica", "logistic-network"),
    ("rede_circuito", "circuit-network"), ("manufacture", "manufacturing"), ("manufatura", "manufacturing"),
    ("trapacas", "cheats"), ("mineracao", "mining"), ("planetas", "planets"), ("comb", "combat"),
    ("tra", None), ("zzz", None), ("", None),
])
def test_resolve_ids_aliases_and_unique_prefix(raw, expected):
    assert T.resolve(raw) == expected


def test_every_alias_resolves_to_exactly_its_tag():
    for t in T.TAGS:
        for a in (t.id, t.label, *t.aliases):
            assert T.resolve(a) == t.id, (t.id, a)


def test_parse_commands():
    p = T.parse_search("cargo $trains $logistics -$combat")
    assert (p.text, p.include, p.exclude, p.unknown) == ("cargo", ["trains", "logistics"], ["combat"], [])
    assert T.parse_search("$trains").include == ["trains"] and T.parse_search("$trains").text == ""
    p = T.parse_search("$trem -$combate fast belt $xyz")
    assert p.include == ["trains"] and p.exclude == ["combat"] and p.text == "fast belt" and p.unknown == ["xyz"]
    assert T.parse_search("$").has_tags is False          # ainda digitando
    assert T.parse_search("hello world").has_tags is False
    p = T.parse_search("$combat -$combat")                  # a última ocorrência vence
    assert p.include == [] and p.exclude == ["combat"]
    p = T.parse_search("-$combat $combat")
    assert p.include == ["combat"] and p.exclude == []


def test_suggest_prefix_alias_and_exclusion():
    assert [t.id for t in T.suggest("tr")][:2] == ["transportation", "trains"] or {"trains", "transportation"} <= {t.id for t in T.suggest("tr")}
    assert T.suggest("trem")[0].id == "trains"
    assert len(T.suggest("")) == 18
    assert "trains" not in {t.id for t in T.suggest("tr", {"trains"})}
    assert "logistic-network" in {t.id for t in T.suggest("rede")}
    assert T.suggest("qqq") == []


def test_replace_tag_tokens_keeps_text():
    assert T.replace_tag_tokens("cargo $trains -$combat fast", ["logistics"], ["armor"]) == "cargo fast $logistics -$armor "
    assert T.replace_tag_tokens("cargo $trains", [], []) == "cargo"


def test_current_token():
    assert T.current_token("cargo $tr", 9) == (6, "$tr")
    assert T.current_token("$trains -$co fast", 12) == (8, "-$co")


# ---------- cliente: forma da requisição e semântica ----------
def make_client(handler, tmp_path):
    http = httpx.Client(transport=httpx.MockTransport(handler), headers={"User-Agent": "t"}, follow_redirects=False)
    return pc.PortalClient(tmp_path / "cache", http, min_interval=0, retries=2, backoff=0)


def entry(name, tags, downloads=1):
    return {"name": name, "title": name.title(), "owner": "o", "summary": "s", "downloads_count": downloads,
            "category": "utilities", "tags": tags, "thumbnail": f"/assets/{'a' * 40}.thumb.png",
            "factorio_versions": ["2.0", "1.1"], "latest_release_version": "1.0.0", "updated_at": "2025-01-01T00:00:00.1"}


def test_search_request_body_and_normalization(tmp_path):
    seen = {}

    def h(req):
        seen["method"], seen["url"], seen["body"] = req.method, str(req.url), json.loads(req.content)
        return httpx.Response(200, json={"pagination": {"count": 7, "page": 2, "page_count": 1, "page_size": 20},
                                         "results": [entry("a", ["trains"])]})

    c = make_client(h, tmp_path)
    items, total = c.search_api(("bob", "SECRET"), query=" cargo ", tags=["trains", "logistics"], exclude_tags=["combat"],
                                categories=["utilities"], sort="downloads", version="2.0.77", page=2)
    b = seen["body"]
    assert seen["method"] == "POST" and seen["url"] == "https://mods.factorio.com/api/search"
    assert b["tag"] == ["trains", "logistics"] and b["exclude_tag"] == ["combat"] and b["category"] == ["utilities"]
    assert b["query"] == "cargo" and b["sort_attribute"] == "most_downloads" and b["version"] == "2.0.77"
    assert b["page"] == 2 and b["page_size"] == 20 and b["show_deprecated"] is False
    assert b["username"] == "bob" and b["token"] == "SECRET" and "SECRET" not in seen["url"]
    assert total == 7 and items[0]["tags"] == ["trains"] and items[0]["fv"] == "2.0" and items[0]["version"] == "1.0.0"
    assert items[0]["thumb"].startswith("/assets/")


def test_search_omits_empty_filters(tmp_path):
    seen = {}

    def h(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"pagination": {"count": 0}, "results": []})

    make_client(h, tmp_path).search_api(("u", "t"))
    assert not ({"tag", "exclude_tag", "category", "query", "version"} & set(seen["body"]))


def test_multiple_tags_is_server_union_and_client_enforces_all(tmp_path):
    data = [entry("both", ["trains", "logistics"]), entry("only_t", ["trains"]), entry("only_l", ["logistics"])]
    calls = []

    def h(req):
        calls.append(json.loads(req.content))
        return httpx.Response(200, json={"pagination": {"count": 3}, "results": data})

    c = make_client(h, tmp_path)
    items = c.search_api_all(("u", "t"), tags=["trains", "logistics"], version="2.0.77")
    assert [m["name"] for m in items] == ["both"]
    assert calls[0]["page_size"] == 20000 and calls[0]["tag"] == ["trains", "logistics"]
    c.search_api_all(("u", "t"), tags=["trains", "logistics"], version="2.0.77")   # cache: sem nova requisição
    assert len(calls) == 1
    assert len(c.search_api_all(("u", "t"), require_all_tags=False, tags=["trains", "logistics"], version="2.0.77")) == 3


def test_search_errors_mapped(tmp_path):
    with pytest.raises(pc.AuthRequired):
        make_client(lambda r: httpx.Response(403, json={"message": "Invalid username or token"}), tmp_path).search_api(("u", "t"))
    with pytest.raises(pc.PortalError, match="not a valid choice"):
        make_client(lambda r: httpx.Response(400, json={"message": "errors: {'tag': [\"'x' is not a valid choice\"]}"}),
                    tmp_path).search_api(("u", "t"), tags=["x"])
    with pytest.raises(pc.AuthRequired):
        make_client(lambda r: httpx.Response(200), tmp_path).search_api(None)

    def down(req):
        raise httpx.ConnectError("down")

    with pytest.raises(pc.PortalOffline):
        make_client(down, tmp_path).search_api(("u", "t"))


def test_token_never_reaches_logs_or_error_text(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(pc.PortalError) as ei:
        make_client(lambda r: httpx.Response(500), tmp_path).search_api(("bob", "TOPSECRET"))
    assert "TOPSECRET" not in str(ei.value) and "TOPSECRET" not in caplog.text


def test_tag_counts_cached(tmp_path):
    n = {"calls": 0}

    def h(req):
        n["calls"] += 1
        return httpx.Response(200, json={"pagination": {"count": 523}, "results": []})

    c = make_client(h, tmp_path)
    assert c.tag_counts(("u", "t"), ["trains", "combat"], "2.0.77", False) == {"trains": 523, "combat": 523}
    c.tag_counts(("u", "t"), ["trains", "combat"], "2.0.77", False)
    assert n["calls"] == 2


def test_thumbnail_from_search_path_skips_full(tmp_path):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 16
    hosts = []

    def h(req):
        hosts.append(req.url.host)
        return httpx.Response(200, content=png)

    c = make_client(h, tmp_path)
    assert c.thumbnail("M", "/assets/" + "a" * 40 + ".thumb.png").read_bytes() == png
    assert hosts == ["assets-mod.factorio.com"]
    assert c.thumbnail("N", "https://evil.example/x.png") is None
