"""HTTP client shared by the chain adapters: browser identity, pauses and bounded retries."""

import time
from collections.abc import Callable

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# A rate-limited request waits longer than a failing one, and never more than this.
RATE_LIMIT_BACKOFF_FACTOR = 4
RETRY_AFTER_CAP_SECONDS = 60.0


class FetchError(RuntimeError):
    """A request failed after the retries allowed for it; `url` is the failing page."""

    def __init__(self, url: str, message: str) -> None:
        super().__init__(f"{url}: {message}")
        self.url = url
        self.error = message


class Fetcher:
    """GETs one page at a time, politely: browser identity, a pause and bounded retries.

    Timeouts, 429 and 5xx are retried with exponential backoff; other 4xx are final. The client
    and the sleep are injectable so tests use an `httpx.MockTransport` and no real waiting.
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        delay: float = 1.5,
        retries: int = 3,
        backoff: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client or httpx.Client(timeout=30.0)
        self._delay = delay
        self._retries = retries
        self._backoff = backoff
        self._sleep = sleep
        self._requests = 0

    def close(self) -> None:
        self._client.close()

    def get(self, url: str) -> httpx.Response:
        """Return a successful response or raise `FetchError` with the URL that failed."""
        for attempt in range(self._retries + 1):
            self._pause()
            try:
                response = self._client.get(url, headers={"User-Agent": USER_AGENT})
            except httpx.TimeoutException as exc:
                if attempt == self._retries:
                    raise FetchError(url, f"timeout: {exc}") from exc
                self._wait(attempt)
                continue
            except httpx.HTTPError as exc:
                raise FetchError(url, str(exc)) from exc
            if response.status_code == 429:
                if attempt == self._retries:
                    raise FetchError(url, "HTTP 429")
                self._wait(attempt, rate_limited=True, retry_after=_retry_after(response))
                continue
            if response.status_code >= 500:
                if attempt == self._retries:
                    raise FetchError(url, f"HTTP {response.status_code}")
                self._wait(attempt)
                continue
            if response.status_code >= 400:
                raise FetchError(url, f"HTTP {response.status_code}")
            return response
        raise AssertionError("unreachable")

    def _pause(self) -> None:
        if self._requests and self._delay:
            self._sleep(self._delay)
        self._requests += 1

    def _wait(
        self, attempt: int, *, rate_limited: bool = False, retry_after: float | None = None
    ) -> None:
        if rate_limited and retry_after is not None:
            self._sleep(min(retry_after, RETRY_AFTER_CAP_SECONDS))
        elif self._backoff:
            factor = RATE_LIMIT_BACKOFF_FACTOR if rate_limited else 1
            self._sleep(self._backoff * factor * 2**attempt)


def _retry_after(response: httpx.Response) -> float | None:
    """Seconds from a numeric `Retry-After` header, or None when it is absent or not numeric."""
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None
