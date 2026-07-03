from gapfinder import worklist, contract, search


def test_build_worklist_tiers_sources_and_validates():
    sources = [
        search.SearchResult(url="https://www.nytimes.com/a", title="NYT piece", text="body one"),
        search.SearchResult(url="https://genshin.fandom.com/x", title="Fan wiki", text="won XYZ award"),
    ]
    wl = worklist.build_worklist(
        campaign="disability-pride-2026",
        subject={"name": "Corina Boettger", "wikidata_id": "Q1"},
        coverage=sources,
        seed_claims=[],
    )
    contract.validate_worklist(wl)  # must not raise
    tiers = {s["domain"]: s["rsp_tier"] for s in wl["sources"]}
    assert tiers["nytimes.com"] == "GENERALLY_RELIABLE"
    assert tiers["genshin.fandom.com"] == "USER_GENERATED"
    assert wl["sources"][0]["source_id"] == "s1"
    assert wl["sources"][0]["fetched_text"] == "body one"


def test_write_and_reload(tmp_path):
    wl = worklist.build_worklist("c", {"name": "N"}, [], [])
    path = worklist.write_worklist(tmp_path, wl)
    assert path.exists()
    import json
    contract.validate_worklist(json.loads(path.read_text()))
