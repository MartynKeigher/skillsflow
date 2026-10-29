import email.message
import io
import time
import urllib.error

from skillsflow.github import GitHub


def rate_limited(reset_in: int) -> urllib.error.HTTPError:
    headers = email.message.Message()
    headers["X-RateLimit-Remaining"] = "0"
    headers["X-RateLimit-Reset"] = str(int(time.time()) + reset_in)
    return urllib.error.HTTPError("https://api.github.com/x", 403, "rate limited", headers, io.BytesIO(b""))


def test_a_long_rate_limit_stops_api_calls_for_the_run(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        raise rate_limited(3600)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda s: (_ for _ in ()).throw(AssertionError("must not wait an hour")))
    gh = GitHub(token="t")
    assert gh.repo("a/b") is None
    assert gh.exhausted
    assert gh.repo("c/d") is None
    assert len(calls) == 1
