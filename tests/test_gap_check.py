"""Gap-check verdict logic against a fake MediaWiki/Wikidata session."""
import copy

from gapfinder import cli


class FakeSession:
    """Routes get_json calls by params, mimicking enwiki + wikidata APIs."""

    def __init__(self, *, exact_page=None, wbsearch_hits=None, sitelinks=None,
                 search_titles=None):
        self.exact_page = exact_page          # page dict for the exact-title query
        self.wbsearch_hits = wbsearch_hits or []
        self.sitelinks = sitelinks or {}      # qid -> sitelinks dict
        self.search_titles = search_titles or []

    def get_json(self, url, params):
        action = params.get("action")
        if action == "wbsearchentities":
            return {"search": copy.deepcopy(self.wbsearch_hits)}
        if action == "wbgetentities":
            qid = params["ids"]
            return {"entities": {qid: {"sitelinks": copy.deepcopy(self.sitelinks.get(qid, {}))}}}
        if params.get("list") == "logevents":
            return {"query": {"logevents": []}}
        if params.get("list") == "search":
            return {"query": {"search": [{"title": t} for t in self.search_titles]}}
        # exact-title / draft query
        titles = params.get("titles", "")
        if titles.startswith("Draft:"):
            return {"query": {"pages": [{"title": titles, "missing": True}]}}
        if self.exact_page is None:
            return {"query": {"pages": [{"title": titles, "missing": True}]}}
        return {"query": {"pages": [copy.deepcopy(self.exact_page)]}}


def test_disambiguation_page_is_not_reported_as_exists():
    # "Mary Johnson" resolves to a disambiguation page, not the person's article.
    session = FakeSession(exact_page={
        "title": "Mary Johnson",
        "pageprops": {"disambiguation": ""},
    })
    r = cli.check_gap(session, "Mary Johnson")
    assert r.status == cli.STATUS_GAP
    assert r.is_disambig is True
    assert any("disambiguation" in n for n in r.notes)


def test_regular_article_still_reports_exists():
    session = FakeSession(exact_page={"title": "Ada Lovelace"})
    r = cli.check_gap(session, "Ada Lovelace")
    assert r.status == cli.STATUS_EXISTS
    assert r.is_disambig is False


def test_disambig_title_still_runs_fuzzy_search():
    # The person may exist under a qualified title like "Mary Johnson (artist)".
    session = FakeSession(
        exact_page={"title": "Mary Johnson", "pageprops": {"disambiguation": ""}},
        search_titles=["Mary Johnson (artist)"],
    )
    r = cli.check_gap(session, "Mary Johnson")
    assert r.search_hits == ["Mary Johnson (artist)"]


def test_wikidata_prefers_exact_label_match():
    # Hit #1 is a namesake company; the exact-label human is hit #2.
    session = FakeSession(wbsearch_hits=[
        {"id": "Q111", "label": "Mary Johnson Ltd", "description": "textile company"},
        {"id": "Q222", "label": "Mary Johnson", "description": "American artist"},
    ])
    wd = cli.check_wikidata(session, "Mary Johnson")
    assert wd["wikidata_id"] == "Q222"
    assert wd["description"] == "American artist"


def test_wikidata_falls_back_to_first_hit_without_exact_match():
    session = FakeSession(wbsearch_hits=[
        {"id": "Q111", "label": "Mary Johnson Ltd", "description": "textile company"},
    ])
    wd = cli.check_wikidata(session, "Mary Johnson")
    assert wd["wikidata_id"] == "Q111"
    assert wd["description"] == "textile company"


def test_wikidata_driven_verdict_carries_identity_note():
    # EXISTS came only from a Wikidata sitelink — the human must be able to
    # check it's the right person, so the entity description is surfaced.
    session = FakeSession(
        wbsearch_hits=[{"id": "Q333", "label": "Jane Doe", "description": "Australian swimmer"}],
        sitelinks={"Q333": {"enwiki": {"title": "Jane Doe"}}},
    )
    r = cli.check_gap(session, "Jane Doe")
    assert r.status == cli.STATUS_EXISTS
    assert any("Australian swimmer" in n and "Q333" in n for n in r.notes)


def test_gap_row_detail_lists_near_miss_search_hits():
    r = cli.GapResult(name="Sinead Burke", status=cli.STATUS_GAP,
                      search_hits=["Sinéad Burke", "Burke (surname)"])
    detail = cli._row_detail(r)
    assert "Sinéad Burke" in detail
    assert "Burke (surname)" in detail
