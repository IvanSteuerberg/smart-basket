"""`smart-basket-api`: serve the API with uvicorn."""

import os

import uvicorn

from smart_basket.config import get_settings


def main() -> None:
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
