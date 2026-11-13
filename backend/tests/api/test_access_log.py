"""Access log of the API: the query string, which may carry an address, is never logged."""

import logging

from smart_basket.api.__main__ import QueryStringFilter


def access_record(path: str) -> logging.LogRecord:
    """The record uvicorn writes for one request: client, method, path, version and status."""
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", path, "1.1", 200),
        None,
    )


def test_access_log_drops_the_query_string_and_keeps_the_path():
    record = access_record("/api/geocode?q=Calle Ancha 1")
    assert QueryStringFilter().filter(record) is True
    logged = logging.Formatter("%(message)s").format(record)
    assert "Calle Ancha" not in logged
    assert "/api/geocode" in logged
