"""Scheduler-owned failure categories; exception contents never become logs."""
import random
import socket
import ssl
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx


class TaskFailure(Exception):
    def __init__(self, code, *, retryable=False, skipped=False, retry_after=0):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.skipped = skipped
        self.retry_after = retry_after


class InterruptedTask(Exception):
    pass


class DatabaseUnavailable(Exception):
    pass


def classify_error(error: Exception) -> TaskFailure:
    if isinstance(error, TaskFailure):
        return error
    cause = error
    seen = set()
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, ssl.SSLError):
            return TaskFailure('tls_error')
        cause = cause.__cause__ or cause.__context__
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        delay = 0
        header = error.response.headers.get('Retry-After', '')
        try:
            delay = max(0, float(header))
        except ValueError:
            try:
                delay = max(0, (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                pass
        return TaskFailure(f'http_{status}', retryable=status in {408, 429} or 500 <= status < 600,
                           skipped=status in {401, 403, 404, 410}, retry_after=delay)
    if isinstance(error, socket.gaierror):
        return TaskFailure('dns_error', retryable=True)
    if isinstance(error, httpx.TimeoutException):
        return TaskFailure('timeout', retryable=True)
    if isinstance(error, (httpx.NetworkError, httpx.RemoteProtocolError, ConnectionError, OSError)):
        return TaskFailure('connect_error', retryable=True)
    if isinstance(error, (ValueError, TypeError, KeyError, AttributeError)):
        return TaskFailure('malformed_response')
    return TaskFailure('task_error')


def retry_delay(attempt: int, failure: TaskFailure, base=5.0, cap=300.0, rng=random.random):
    return max(failure.retry_after, min(cap, base * 2 ** max(0, attempt - 1)) * (0.5 + 0.5 * rng()))
