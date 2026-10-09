import httpx
import pytest

from mevzuat_git import fetch as fetch_mod
from mevzuat_git.fetch import Fetcher, NotFound, cache_path, decode_html


def make_fetcher(tmp_path, handler, **kw):
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return Fetcher(cache_dir=tmp_path, min_interval=0, client=client, **kw)


def test_cache_path_is_readable_and_keeps_query(tmp_path):
    p = cache_path(
        "https://www.mevzuat.gov.tr/anasayfa/MevzuatFihristDetayIframe?"
        "MevzuatTur=1&MevzuatNo=193&MevzuatTertip=4",
        tmp_path,
    )
    assert p == tmp_path / "www.mevzuat.gov.tr/anasayfa/" \
        "MevzuatFihristDetayIframe__MevzuatTur=1&MevzuatNo=193&MevzuatTertip=4"


def test_second_get_comes_from_cache(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, content=b"<html>ok</html>",
                              headers={"content-type": "text/html"})

    f = make_fetcher(tmp_path, handler)
    url = "https://www.resmigazete.gov.tr/eskiler/2024/08/20240802.htm"
    first = f.get(url)
    assert first.from_cache is False
    r = f.get(url)
    assert r.from_cache is True and r.content == b"<html>ok</html>"
    assert len(calls) == 1
    # The day of the fetch comes back with the cached copy: what the text holds on.
    assert r.fetched_at is not None and r.fetched_at.date() == first.fetched_at.date()


def test_user_agent_is_sent(tmp_path):
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, content=b"x")

    client = httpx.Client(transport=httpx.MockTransport(handler),
                          headers={"User-Agent": fetch_mod.USER_AGENT})
    Fetcher(cache_dir=tmp_path, min_interval=0, client=client).get("https://example.org/a")
    assert seen["ua"].startswith("mevzuat-git/")


def test_mevzuat_error_redirect_is_not_found_and_cached(tmp_path):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if "errorpage" in request.url.path:
            return httpx.Response(200, content=b"error page")
        return httpx.Response(302, headers={"location": "/anasayfa/errorpage?code=404"})

    f = make_fetcher(tmp_path, handler)
    url = "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=193&MevzuatTur=1&MevzuatTertip=5"
    with pytest.raises(NotFound):
        f.get(url)
    n = len(calls)
    with pytest.raises(NotFound):
        f.get(url)
    assert len(calls) == n  # the miss was cached


def test_retries_transport_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda s: None)
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) < 3:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, content=b"finally")

    f = make_fetcher(tmp_path, handler)
    assert f.get("https://www.mevzuat.gov.tr/x").content == b"finally"
    assert len(attempts) == 3


def test_offline_mode_refuses_network(tmp_path):
    f = make_fetcher(tmp_path, lambda r: httpx.Response(200), offline=True)
    with pytest.raises(RuntimeError):
        f.get("https://www.mevzuat.gov.tr/y")


def test_decode_html_handles_both_sites():
    # mevzuat.gov.tr: declares windows-1254 but is UTF-8
    assert decode_html("GELİR VERGİSİ".encode()) == "GELİR VERGİSİ"
    # resmigazete.gov.tr: windows-1254
    assert decode_html("Değişiklik".encode("cp1254")) == "Değişiklik"
