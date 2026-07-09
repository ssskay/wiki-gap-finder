import json
import logging

from gapfinder import search
from tests.conftest import FIXTURES


def test_fake_backend_returns_seeded_results():
    backend = search.FakeBackend({"corina": [
        search.SearchResult(url="https://x.com", title="X", text="body")]})
    results = search.search_web("corina award", backend=backend)
    assert results[0].url == "https://x.com"
    assert results[0].text == "body"


def test_ddg_html_is_parsed_into_results():
    html = (FIXTURES / "ddg_result.html").read_text()
    results = search.DDGBackend._parse(html)
    assert [r.url for r in results] == ["https://news.com/story-1", "https://blog.example/story-2"]
    assert results[0].title == "Story One Title"


def test_search_result_roundtrips_to_dict():
    r = search.SearchResult(url="https://x.com", title="T", text="B")
    assert r.to_dict() == {"url": "https://x.com", "title": "T", "text": "B"}


def test_firecrawl_missing_binary_degrades_to_empty():
    def boom(*a, **k):
        raise FileNotFoundError("firecrawl not on PATH")
    backend = search.FirecrawlBackend(runner=boom)
    assert backend.search("q", 5) == []


def test_firecrawl_bad_json_degrades_to_empty():
    class Proc:
        returncode, stdout, stderr = 0, "not json{", ""
    backend = search.FirecrawlBackend(runner=lambda *a, **k: Proc())
    assert backend.search("q", 5) == []


def test_firecrawl_unexpected_shape_degrades_to_empty():
    class Proc:
        returncode, stdout, stderr = 0, '{"data": {"not": "a list"}}', ""
    backend = search.FirecrawlBackend(runner=lambda *a, **k: Proc())
    assert backend.search("q", 5) == []


def test_firecrawl_parses_current_cli_shape_data_web():
    # The firecrawl CLI (2026) wraps results as {"data": {"web": [...]}} with a
    # "description" field — not the flat list the backend originally expected.
    payload = {"success": True, "data": {"web": [
        {"url": "https://en.wikipedia.org/wiki/Nujeen_Mustafa",
         "title": "Nujeen Mustafa - Wikipedia",
         "description": "Kurdish Syrian refugee and activist", "position": 1},
        {"url": "https://example.org/profile", "title": "Profile",
         "description": "second hit", "position": 2},
    ]}}
    class Proc:
        returncode, stdout, stderr = 0, json.dumps(payload), ""
    backend = search.FirecrawlBackend(runner=lambda *a, **k: Proc())
    results = backend.search("q", 5)
    assert [r.url for r in results] == [
        "https://en.wikipedia.org/wiki/Nujeen_Mustafa", "https://example.org/profile"]
    assert results[0].text == "Kurdish Syrian refugee and activist"


def test_ddg_redirect_links_are_decoded_to_real_urls():
    # DDG result anchors are //duckduckgo.com/l/?uddg=<encoded> redirects; the
    # real URL must come out, or every source tiers as duckduckgo.com -> UNRATED.
    html = ('<a rel="nofollow" class="result__a" '
            'href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fnews.com%2Fstory-1&amp;rut=abc">'
            'Story One</a>')
    results = search.DDGBackend._parse(html)
    assert results[0].url == "https://news.com/story-1"


def test_ddg_zero_results_warns_about_bot_challenge(caplog):
    # DDG serves an HTTP 202 challenge page to non-browser clients; parsing it
    # yields nothing. That must be loud, not a silent empty worklist.
    class FakeSession:
        def get_text(self, url, params):
            return "<html>anomaly detected</html>"
    backend = search.DDGBackend(FakeSession())
    with caplog.at_level(logging.WARNING):
        assert backend.search("q", 5) == []
    assert any("challenge" in rec.message.lower() or "blocked" in rec.message.lower()
               for rec in caplog.records)
