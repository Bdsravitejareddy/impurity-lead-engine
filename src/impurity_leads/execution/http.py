"""Lease-aware synchronous HTTP with shared host pacing and bounded bodies."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

import httpx

from impurity_leads.execution.retry import TaskFailure


@dataclass
class _Host:
    lock: threading.Lock = field(default_factory=threading.Lock)
    next_request: float = 0.0


class HostGate:
    """Serialize a host, including www aliases, across every client sharing this gate."""

    def __init__(self, delay_seconds=1.0):
        self.delay_seconds = max(0.0, delay_seconds)
        self._hosts = {}
        self._lock = threading.Lock()

    @contextmanager
    def hold(self, url, context):
        host = (httpx.URL(url).host or "").lower().rstrip(".")
        if host.startswith("www."):
            host = host[4:]
        with self._lock:
            state = self._hosts.setdefault(host, _Host())
        while True:
            context.check()
            if state.lock.acquire(timeout=.05):
                break
        sent = False
        try:
            while True:
                context.check()
                remaining = state.next_request - time.monotonic()
                if remaining <= 0:
                    break
                context.runner.stop.wait(min(.05, remaining))
            # Renew after waiting, immediately before any network operation.
            context.before_request()
            sent = True
            yield
        finally:
            if sent:
                state.next_request = time.monotonic() + self.delay_seconds
            state.lock.release()


class CrawlClient:
    """Own no retries: return HTTP statuses and propagate transport errors intact."""

    def __init__(self, context, settings, gate, client=None):
        self.context = context
        self.settings = settings
        self.gate = gate
        self._owned = client is None
        self._timeout = httpx.Timeout(settings.request_timeout_seconds,
                                      connect=settings.connect_timeout_seconds,
                                      pool=settings.connect_timeout_seconds)
        self.client = client if client is not None else httpx.Client(
            timeout=self._timeout, verify=True, trust_env=False,
            follow_redirects=False, headers={"User-Agent": settings.user_agent},
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        if self._owned:
            self.client.close()

    def get(self, url, params=None, headers=None) -> httpx.Response:
        request = self.client.build_request("GET", url, params=params, headers=headers, timeout=self._timeout)
        history = []
        while True:
            self.context.check()
            if request.url.scheme not in {"https", "http"}:
                raise TaskFailure("unsupported_scheme")
            with self.gate.hold(request.url, self.context):
                started = time.monotonic()

                def check_elapsed():
                    self.context.check()
                    if time.monotonic() - started >= self.settings.request_timeout_seconds:
                        raise httpx.ReadTimeout("request_time_limit", request=request)

                response = self.client.send(request, stream=True, follow_redirects=False)
                try:
                    check_elapsed()
                    chunks = []
                    size = 0
                    for chunk in response.iter_bytes():
                        check_elapsed()
                        size += len(chunk)
                        if size > self.settings.max_response_bytes:
                            raise TaskFailure("response_too_large")
                        chunks.append(chunk)
                    check_elapsed()
                    # Keep httpx response metadata and decoded-content semantics intact.
                    response._content = b"".join(chunks)
                finally:
                    response.close()
            response.history = list(history)
            redirect = response.next_request
            if redirect is None:
                return response
            if request.url.scheme == "https" and redirect.url.scheme == "http":
                raise TaskFailure("https_downgrade")
            if len(history) >= 10:
                raise httpx.TooManyRedirects("redirect_limit", request=request)
            history.append(response)
            # httpx constructs this request and removes credentials across origins.
            request = redirect
