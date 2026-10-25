"""Compare the contract (docs/api/openapi.yaml) with the routes the app really serves.

The app serves the contract itself at /api/v1/openapi.json (Swagger /api/v1/docs), so there is
nothing to regenerate. This script shows what differs and can save the served spec as JSON:

    uv run python scripts/export_openapi.py                 # report only
    uv run python scripts/export_openapi.py --json out.json # also save the served spec
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.openapi.utils import get_openapi  # noqa: E402

from app.main import API_PREFIX, app  # noqa: E402

METHODS = {"get", "post", "put", "patch", "delete"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, help="write the served OpenAPI document here")
    args = parser.parse_args()

    served = app.openapi()
    contract = {(p, m) for p, item in served["paths"].items() for m in item if m in METHODS}
    generated = get_openapi(title="app", version="0", routes=app.routes)
    routed = {
        (p.removeprefix(API_PREFIX), m)
        for p, item in generated["paths"].items()
        for m in item
        if m in METHODS
    }
    for title, ops in (
        ("In the contract, not implemented yet", contract - routed),
        ("Implemented, missing in the contract (must be empty)", routed - contract),
    ):
        print(f"{title}: {len(ops)}")
        for path, method in sorted(ops):
            print(f"  {method.upper():6} {path}")
    if args.json:
        args.json.write_text(json.dumps(served, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved {args.json}")
    return 1 if routed - contract else 0


if __name__ == "__main__":
    raise SystemExit(main())
