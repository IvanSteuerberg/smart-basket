"""Supervised unlock experiment runner (T1 / T2) for Alcampo and Carrefour.

Implements the protocol in experiments/supervised-unlock/README.md:
- No automated circumvention (NFR-07): if an interactive challenge appears, the
  visible browser window stays open for the human author to complete it.
- Passive measurement via page.on("response") during normal navigation, never
  synthetic fetch()/httpx calls.
- Persistent browser profile per chain under profiles/<chain> (git-ignored).
- Appends one telemetry record per run to results.jsonl and saves 2-3 contract
  samples under samples/ (git-ignored).
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import time
from typing import Any

from playwright.sync_api import Response, sync_playwright

BASE_DIR = Path(__file__).resolve().parent
PROFILES_DIR = BASE_DIR / "profiles"
SAMPLES_DIR = BASE_DIR / "samples"
RESULTS_FILE = BASE_DIR / "results.jsonl"

CHAIN_CONFIG: dict[str, dict[str, str]] = {
    "alcampo": {
        "entry_url": "https://www.compraonline.alcampo.es/categories/frescos/OC2112",
        "token_cookie": "aws-waf-token",
    },
    "carrefour": {
        "entry_url": "https://www.carrefour.es/supermercado/",
        "token_cookie": "cf_clearance",
    },
}

GATE_TITLES = (
    "human verification",
    "just a moment",
    "attention required",
    "un momento",
)


def _is_gate_title(title: str) -> bool:
    lowered = title.strip().lower()
    return any(marker in lowered for marker in GATE_TITLES)


def run_unlock(
    chain: str,
    phase: str,
    profile_label: str,
    timeout_s: int = 300,
    settle_s: int = 25,
    channel: str | None = "chrome",
) -> dict[str, Any]:
    cfg = CHAIN_CONFIG[chain]
    profile_dir = PROFILES_DIR / chain
    had_profile = profile_dir.exists() and any(profile_dir.iterdir())
    profile_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = PROFILES_DIR / "_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(tmp_dir)
    os.environ["TMP"] = str(tmp_dir)
    os.environ["TMPDIR"] = str(tmp_dir)
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    captured_samples: list[dict[str, Any]] = []
    api_calls = 0
    products_seen = 0

    def _on_response(resp: Response) -> None:
        nonlocal api_calls, products_seen
        ctype = resp.headers.get("content-type", "").lower()
        if resp.request.resource_type not in ("xhr", "fetch", "document"):
            return
        if "json" not in ctype and resp.request.resource_type != "document":
            return
        try:
            body = resp.text()
        except Exception:
            return
        if "json" in ctype:
            api_calls += 1
            lower = body.lower()
            if '"price"' in lower or '"unitprice"' in lower or '"app_price"' in lower:
                products_seen += lower.count('"price"')
                if len(captured_samples) < 3:
                    captured_samples.append(
                        {
                            "url": resp.url,
                            "status": resp.status,
                            "content_type": ctype,
                            "body_preview": body[:50000],
                        }
                    )

    start_ts = time.monotonic()
    gate_type = "none"
    notes_parts: list[str] = []

    with sync_playwright() as p:
        launch_kwargs: dict[str, Any] = {
            "user_data_dir": str(profile_dir),
            "headless": False,
            "locale": "es-ES",
            "viewport": {"width": 1366, "height": 900},
        }
        if channel:
            launch_kwargs["channel"] = channel
        ctx = p.chromium.launch_persistent_context(**launch_kwargs)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("response", _on_response)

        resp = page.goto(cfg["entry_url"], wait_until="domcontentloaded", timeout=60000)
        initial_status = resp.status if resp else 0
        page.wait_for_timeout(3000)
        title = page.title()

        if _is_gate_title(title) or initial_status in (403, 405):
            # Give a brief window for a silent token renewal before asking the human author.
            page.wait_for_timeout(5000)
            title = page.title()
            cookies = {c["name"]: c["value"] for c in ctx.cookies()}
            if not _is_gate_title(title) and (
                cfg["token_cookie"] in cookies or products_seen > 0
            ):
                gate_type = "silent"
            else:
                print(
                    f"[{chain}] Interactive gate detected (status={initial_status}, title={title!r}). "
                    f"Waiting up to {timeout_s}s for the author to complete it in the visible browser window..."
                )
                deadline = time.monotonic() + timeout_s
                unlocked = False
                while time.monotonic() < deadline:
                    page.wait_for_timeout(2000)
                    title = page.title()
                    cookies = {c["name"]: c["value"] for c in ctx.cookies()}
                    if not _is_gate_title(title) and (
                        cfg["token_cookie"] in cookies or products_seen > 0
                    ):
                        unlocked = True
                        break
                gate_type = "interactive_author" if unlocked else "hard_block"

        if gate_type != "hard_block":
            print(
                f"[{chain}] Gate clear (gate_type={gate_type}). "
                f"Observing natural navigation for {settle_s}s..."
            )
            page.wait_for_timeout(settle_s * 1000)

        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        has_token = cfg["token_cookie"] in cookies
        notes_parts.append(f"initial_status={initial_status}")
        notes_parts.append(f"final_title={page.title()!r}")
        notes_parts.append(f"has_{cfg['token_cookie']}={has_token}")
        notes_parts.append(f"had_existing_profile={had_profile}")
        ctx.close()

    elapsed_s = round(time.monotonic() - start_ts, 1)

    for idx, sample in enumerate(captured_samples, 1):
        sample_path = SAMPLES_DIR / f"{chain}-{phase.lower()}-{idx}.json"
        sample_path.write_text(
            json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    record = {
        "ts": datetime.now(UTC).isoformat(),
        "chain": chain,
        "phase": phase,
        "profile": profile_label,
        "gate_type": gate_type,
        "pass_seconds": elapsed_s,
        "api_calls": api_calls,
        "products_seen": products_seen,
        "notes": "; ".join(notes_parts),
    }
    with RESULTS_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return record


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run T1/T2 supervised unlock experiment for Alcampo or Carrefour."
    )
    parser.add_argument("chain", choices=sorted(CHAIN_CONFIG))
    parser.add_argument("--phase", default="T1", choices=["T1", "T2"])
    parser.add_argument(
        "--profile",
        default="fresh",
        help="Profile state label, e.g. fresh, warm(T+1h), warm(T+24h), warm(T+72h), warm(T+7d)",
    )
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--settle", type=int, default=25)
    parser.add_argument("--channel", default="chrome", help="Browser channel (chrome, msedge, or empty)")
    args = parser.parse_args()
    run_unlock(
        chain=args.chain,
        phase=args.phase,
        profile_label=args.profile,
        timeout_s=args.timeout,
        settle_s=args.settle,
        channel=args.channel or None,
    )


if __name__ == "__main__":
    main()
