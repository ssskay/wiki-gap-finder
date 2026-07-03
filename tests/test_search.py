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
