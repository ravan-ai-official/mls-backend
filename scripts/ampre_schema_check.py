"""
Standalone AMPRE SELECT_FIELDS diagnostic — no Django needed.

Reads AMPRE_ODATA_BEARER_TOKEN + AMPRE_ODATA_BASE_URL from .env.prod,
iteratively removes invalid fields from sync_ampre_closed.SELECT_FIELDS
until AMPRE returns 200, prints the bad/valid lists.

Run from repo root:
    python scripts/ampre_schema_check.py
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from urllib.parse import quote

import requests


def load_env_prod() -> dict[str, str]:
    env_path = Path(__file__).resolve().parent.parent / ".env.prod"
    if not env_path.exists():
        sys.exit(f"Missing {env_path}")
    env: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def load_select_fields() -> list[str]:
    """Pull SELECT_FIELDS list literal out of sync_ampre_closed.py without
    triggering Django app loading."""
    source = (
        Path(__file__).resolve().parent.parent
        / "mls" / "management" / "commands" / "sync_ampre_closed.py"
    ).read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "SELECT_FIELDS"
            and isinstance(node.value, ast.List)
        ):
            return [
                el.value for el in node.value.elts
                if isinstance(el, ast.Constant) and isinstance(el.value, str)
            ]
    sys.exit("Could not find SELECT_FIELDS literal in sync_ampre_closed.py")


def main() -> None:
    env = load_env_prod()
    token = env.get("AMPRE_ODATA_BEARER_TOKEN", "")
    base = env.get(
        "AMPRE_ODATA_BASE_URL", "https://query.ampre.ca/odata"
    ).rstrip("/")
    if not token:
        sys.exit("AMPRE_ODATA_BEARER_TOKEN missing from .env.prod")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (compatible; HomeAtlas/1.0; +https://homeatlas.ca)"
        ),
    }
    SAFE_K = "$"
    SAFE_V = "$,()'"

    def encode(params: dict) -> str:
        return "&".join(
            f"{quote(str(k), safe=SAFE_K)}={quote(str(v), safe=SAFE_V)}"
            for k, v in params.items()
        )

    remaining = load_select_fields()
    print(f"Starting with {len(remaining)} SELECT_FIELDS")
    bad: list[str] = []

    while True:
        qs = encode({
            "$top": 1,
            "$filter": "StandardStatus eq 'Closed'",
            "$select": ",".join(remaining),
        })
        r = requests.get(f"{base}/Property?{qs}", headers=headers, timeout=30)
        if r.status_code == 200:
            print(f"OK: {len(remaining)} fields pass validation.")
            break
        m = re.search(r"The property '([^']+)'", r.text)
        if not m:
            print(f"Unexpected {r.status_code}: {r.text[:400]}")
            sys.exit(1)
        bad_field = m.group(1)
        print(f"  bad: {bad_field}")
        bad.append(bad_field)
        remaining.remove(bad_field)

    print()
    print(f"BAD FIELDS ({len(bad)}):")
    for f in bad:
        print(f"  {f!r},")
    print()
    print(f"VALID FIELDS ({len(remaining)}):")
    for f in remaining:
        print(f"  {f!r},")


if __name__ == "__main__":
    main()
