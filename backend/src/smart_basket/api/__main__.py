"""`smart-basket-api`: serve the API with uvicorn."""

import logging
import os

import uvicorn

from smart_basket.config import get_settings


class QueryStringFilter(logging.Filter):
    """Drop the query string from the path uvicorn writes to the access log (NFR-06).

    The geocoding endpoint receives the user's address as `?q=`, so the logged path must keep
    the route and lose the query.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5:
            client, method, path, version, status = args
            if isinstance(path, str):
                record.args = (client, method, path.partition("?")[0], version, status)
        return True


def main() -> None:
    logging.getLogger("uvicorn.access").addFilter(QueryStringFilter())
    uvicorn.run(
        "smart_basket.api.app:app",
        host=os.environ.get("API_HOST", "0.0.0.0"),
        port=int(os.environ.get("API_PORT", "8000")),
        log_level=get_settings().log_level.lower(),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
