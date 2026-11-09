"""Politeness, retries and error mapping of the shared fetcher, against a fake transport."""

import httpx
import pytest

from smart_basket.ingestion.http import Fetcher, FetchError

URL = "https://example.test/api/categories/"


def make_fetcher(handler, *, delay: float = 0.0, backoff: float = 0.0) -> tuple[Fetcher, list]:
    sleeps: list[float] = []
    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = Fetcher(client, delay=delay, backoff=backoff, sleep=sleeps.append)
    return fetcher, sleeps


def test_requests_carry_a_desktop_browser_user_agent():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["agent"] = request.headers["user-agent"]
        return httpx.Response(200, json={})

    make_fetcher(handler)[0].get(URL)
    assert seen["agent"].startswith("Mozilla/5.0")
    assert "Windows" in seen["agent"]


def test_pause_between_requests():
    fetcher, sleeps = make_fetcher(lambda request: httpx.Response(200), delay=1.5)
    fetcher.get(URL)
    fetcher.get(URL)
    assert sleeps == [1.5]


def test_429_is_retried_with_backoff():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url)
        return httpx.Response(429 if len(attempts) == 1 else 200)

    fetcher, sleeps = make_fetcher(handler, backoff=0.5)
    assert fetcher.get(URL).status_code == 200
    assert len(attempts) == 2
    assert sleeps == [0.5]


def test_server_errors_are_retried_three_times_then_fail():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url)
        return httpx.Response(500)

    fetcher, sleeps = make_fetcher(handler, backoff=0.5)
    with pytest.raises(FetchError, match="HTTP 500"):
        fetcher.get(URL)
    assert len(attempts) == 4
    assert sleeps == [0.5, 1.0, 2.0]


def test_other_client_errors_are_not_retried():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url)
        return httpx.Response(404)

    fetcher, _ = make_fetcher(handler, backoff=0.5)
    with pytest.raises(FetchError, match="HTTP 404"):
        fetcher.get(URL)
    assert len(attempts) == 1


def test_timeouts_are_retried():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url)
        raise httpx.ReadTimeout("slow", request=request)

    fetcher, sleeps = make_fetcher(handler, backoff=0.5)
    with pytest.raises(FetchError, match="timeout"):
        fetcher.get(URL)
    assert len(attempts) == 4
    assert sleeps == [0.5, 1.0, 2.0]


def test_network_errors_are_final_and_keep_the_url():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url)
        raise httpx.ConnectError("refused", request=request)

    fetcher, _ = make_fetcher(handler, backoff=0.5)
    with pytest.raises(FetchError) as error:
        fetcher.get(URL)
    assert error.value.url == URL
    assert len(attempts) == 1
