"""PoliteSession etiquette: maxlag on MediaWiki action-API calls."""
import pytest

from gapfinder import cli


class _Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _capture_session(responses):
    """A fake requests.Session recording params and replaying canned responses."""
    calls = []

    class FakeRequestsSession:
        headers = {}

        def get(self, url, params=None, timeout=None):
            calls.append(dict(params or {}))
            return responses.pop(0)

    return FakeRequestsSession(), calls


def test_action_api_calls_send_maxlag(monkeypatch):
    s = cli.PoliteSession()
    fake, calls = _capture_session([_Resp({"query": {}})])
    s._session = fake
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)

    s.get_json(cli.ENWIKI_API, {"action": "query", "format": "json"})
    assert calls[0].get("maxlag") == "5"


def test_non_action_calls_do_not_send_maxlag(monkeypatch):
    # SPARQL / non-MediaWiki endpoints don't understand maxlag.
    s = cli.PoliteSession()
    fake, calls = _capture_session([_Resp({"results": {}})])
    s._session = fake
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)

    s.get_json(cli.WIKIDATA_SPARQL, {"query": "SELECT 1", "format": "json"})
    assert "maxlag" not in calls[0]


def test_maxlag_error_is_retried(monkeypatch):
    # A lagged replica answers HTTP 200 with an error body; that must retry,
    # not surface as an empty/weird result.
    s = cli.PoliteSession()
    lagged = _Resp({"error": {"code": "maxlag", "info": "Waiting for a database"}})
    ok = _Resp({"query": {"pages": []}})
    fake, calls = _capture_session([lagged, ok])
    s._session = fake
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)

    data = s.get_json(cli.ENWIKI_API, {"action": "query", "format": "json"})
    assert data == {"query": {"pages": []}}
    assert len(calls) == 2


def test_caller_params_are_not_mutated(monkeypatch):
    s = cli.PoliteSession()
    fake, _ = _capture_session([_Resp({"query": {}})])
    s._session = fake
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)

    params = {"action": "query", "format": "json"}
    s.get_json(cli.ENWIKI_API, params)
    assert "maxlag" not in params
