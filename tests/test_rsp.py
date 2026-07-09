from pathlib import Path

import gapfinder
from gapfinder import rsp


def test_known_reliable_domain():
    assert rsp.tier_for_domain("nytimes.com")[0] == "GENERALLY_RELIABLE"


def test_user_generated_fandom():
    assert rsp.tier_for_domain("genshin-impact.fandom.com")[0] == "USER_GENERATED"


def test_www_and_subdomain_are_normalized():
    assert rsp.tier_for_domain("www.nytimes.com")[0] == "GENERALLY_RELIABLE"


def test_unknown_domain_is_unrated():
    assert rsp.tier_for_domain("some-random-blog-42.example")[0] == "UNRATED"


def test_tier_for_url_extracts_domain():
    assert rsp.tier_for_url("https://www.imdb.com/name/nm123/")[0] == "GENERALLY_UNRELIABLE"


def test_seed_ships_inside_the_package():
    # The seed must live under gapfinder/ so wheels carry it — at the old
    # repo-root data/ location, every pip install tiered everything UNRATED.
    pkg = Path(gapfinder.__file__).resolve().parent
    assert rsp._SEED_PATH.is_relative_to(pkg)
    assert rsp._SEED_PATH.exists()
