import ssl
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

from impurity_leads.config import Settings
from impurity_leads.execution.http import CrawlClient, HostGate
from impurity_leads.execution.retry import InterruptedTask, TaskFailure, classify_error


class Context:
    def __init__(self):
        self.runner = SimpleNamespace(stop=threading.Event())
        self.renewals = 0

    def check(self):
        if self.runner.stop.is_set():
            raise InterruptedTask()

    def before_request(self):
        self.check()
        self.renewals += 1


def client(handler, *, context=None, gate=None, **settings):
    return CrawlClient(context or Context(), Settings(**settings), gate or HostGate(0),
                       client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_get_returns_404_and_forwards_params_headers_without_retries():
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(404, content=b"missing")
    context = Context()
    with client(handler, context=context) as crawler:
        response = crawler.get("https://example.com/page", params={"q": "test"}, headers={"X-Test": "yes"})
    assert response.status_code == 404 and response.content == b"missing"
    assert len(seen) == context.renewals == 1
    assert seen[0].url.params["q"] == "test" and seen[0].headers["X-Test"] == "yes"


def test_redirect_strips_cross_origin_auth_and_blocks_downgrade():
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "https://other.com/"}) if len(seen) == 1 else httpx.Response(200)
    with client(handler) as crawler:
        assert crawler.get("https://example.com/", headers={"Authorization": "Bearer test"}).status_code == 200
    assert "authorization" not in seen[1].headers
    seen.clear()
    def downgrade(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "http://example.com/"})
    with client(downgrade) as crawler, pytest.raises(TaskFailure) as error:
        crawler.get("https://example.com/")
    assert error.value.code == "https_downgrade" and len(seen) == 1


def test_tls_exception_preserved_for_classifier():
    def handler(request):
        try:
            raise ssl.SSLCertVerificationError("certificate")
        except ssl.SSLError as cause:
            raise httpx.ConnectError("connection", request=request) from cause
    with client(handler) as crawler, pytest.raises(httpx.ConnectError) as error:
        crawler.get("https://example.com/")
    assert classify_error(error.value).code == "tls_error"


def test_response_size_limit_applies_to_streamed_decoded_bytes():
    class Stream(httpx.SyncByteStream):
        closed = False
        def __iter__(self):
            yield b"123"
            yield b"456"
        def close(self):
            self.closed = True
    stream = Stream()
    with client(lambda request: httpx.Response(200, stream=stream), max_response_bytes=5) as crawler:
        with pytest.raises(TaskFailure) as error:
            crawler.get("https://example.com/")
    assert error.value.code == "response_too_large" and stream.closed


def test_stream_time_is_bounded():
    class SlowStream(httpx.SyncByteStream):
        def __iter__(self):
            time.sleep(.02)
            yield b"x"
    with client(lambda request: httpx.Response(200, stream=SlowStream()), request_timeout_seconds=.005) as crawler:
        with pytest.raises(httpx.TimeoutException):
            crawler.get("https://example.com/")


def test_same_host_and_redirect_target_are_serialized_but_other_hosts_run():
    gate = HostGate(0)
    occupied, release, other_done, redirected = (threading.Event() for _ in range(4))
    errors = []
    def handler(request):
        if request.url.path == "/hold":
            occupied.set()
            assert release.wait(2)
        if request.url.host == "start.com":
            return httpx.Response(302, headers={"Location": "https://www.example.com/target"})
        if request.url.path == "/target":
            redirected.set()
        if request.url.host == "other.com":
            other_done.set()
        return httpx.Response(200)
    def get(url):
        try:
            with client(handler, gate=gate) as crawler:
                crawler.get(url)
        except Exception as exc:
            errors.append(exc)
    threads = [threading.Thread(target=get, args=(url,)) for url in
               ("https://example.com/hold", "https://start.com/", "https://other.com/")]
    threads[0].start()
    assert occupied.wait(1)
    for thread in threads[1:]:
        thread.start()
    try:
        assert other_done.wait(1)
        assert not redirected.wait(.05)
    finally:
        release.set()
        for thread in threads:
            thread.join(2)
    assert redirected.is_set() and not errors


def test_stop_interrupts_pacing_wait():
    gate, context = HostGate(10), Context()
    with client(lambda request: httpx.Response(200), context=context, gate=gate) as crawler:
        crawler.get("https://example.com/")
        timer = threading.Timer(.03, context.runner.stop.set)
        timer.start()
        started = time.monotonic()
        try:
            with pytest.raises(InterruptedTask):
                crawler.get("https://www.example.com/second")
        finally:
            timer.join()
    assert time.monotonic() - started < .5


def test_redirect_limit():
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "/again"})
    with client(handler) as crawler, pytest.raises(httpx.TooManyRedirects):
        crawler.get("https://example.com/")
    assert len(seen) == 11


def test_owned_client_uses_tls_no_environment_and_explicit_timeout(monkeypatch):
    original = httpx.Client
    options = []
    def make_client(**kwargs):
        options.append(kwargs)
        return original(transport=httpx.MockTransport(lambda request: httpx.Response(200)), **kwargs)
    monkeypatch.setattr(httpx, "Client", make_client)
    with CrawlClient(Context(), Settings(), HostGate(0)) as crawler:
        assert crawler.get("https://example.com/").status_code == 200
    assert options[0]["verify"] is True
    assert options[0]["trust_env"] is False
    assert options[0]["follow_redirects"] is False
    assert options[0]["timeout"].connect == options[0]["timeout"].pool == 5
    assert options[0]["timeout"].read == options[0]["timeout"].write == 20
    assert crawler.client.is_closed


def test_host_lock_covers_body_consumption_and_releases_on_interruption():
    streaming, release, second_sent = (threading.Event() for _ in range(3))
    gate, context = HostGate(0), Context()
    errors = []
    class BlockingStream(httpx.SyncByteStream):
        def __iter__(self):
            streaming.set()
            assert release.wait(2)
            yield b"body"
    def handler(request):
        if request.url.path == "/first":
            return httpx.Response(200, stream=BlockingStream())
        second_sent.set()
        return httpx.Response(200)
    def get(path, ctx):
        try:
            with client(handler, context=ctx, gate=gate) as crawler:
                crawler.get("https://example.com/" + path)
        except InterruptedTask:
            errors.append("interrupted")
    first = threading.Thread(target=get, args=("first", context))
    second = threading.Thread(target=get, args=("second", Context()))
    first.start()
    assert streaming.wait(1)
    second.start()
    try:
        assert not second_sent.wait(.05)
        context.runner.stop.set()
    finally:
        release.set()
        first.join(2)
        second.join(2)
    assert second_sent.is_set() and errors == ["interrupted"]
