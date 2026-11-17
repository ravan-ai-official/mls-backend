"""
Fetch AMPRE's $metadata, parse the Property entity schema, and report
which fields in sync_ampre_closed.SELECT_FIELDS are not in the schema.

Run inside the backend container (so AMPRE_ODATA_BEARER_TOKEN + base URL
come from Django settings):

    docker run --rm \
      --env-file .env.prod \
      -e DATABASE_URL="sqlite:////tmp/dry_run.db" \
      -e DEBUG=False \
      -v "$(pwd):/app" \
      us-central1-docker.pkg.dev/homeatlas-513912/mls/mls-backend:latest \
      python scripts/ampre_schema_filter.py
"""
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import django
import requests

sys.path.insert(0, "/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
django.setup()

from django.conf import settings  # noqa: E402

from mls.management.commands.sync_ampre_closed import SELECT_FIELDS  # noqa: E402


def main() -> None:
    token = getattr(settings, "AMPRE_ODATA_BEARER_TOKEN", "")
    base = getattr(
        settings, "AMPRE_ODATA_BASE_URL", "https://query.ampre.ca/odata"
    ).rstrip("/")
    if not token:
        sys.exit("AMPRE_ODATA_BEARER_TOKEN not set")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/xml",
        "User-Agent": (
            "Mozilla/5.0 (compatible; HomeAtlas/1.0; +https://homeatlas.ca)"
        ),
    }
    r = requests.get(f"{base}/$metadata", headers=headers, timeout=60)
    r.raise_for_status()

    # OData CSDL namespaces vary by version; find any Property EntityType.
    root = ET.fromstring(r.text)
    valid: set[str] = set()
    for et in root.iter():
        if not et.tag.endswith("EntityType"):
            continue
        if et.attrib.get("Name") != "Property":
            continue
        for prop in et:
            if prop.tag.endswith("Property"):
                name = prop.attrib.get("Name")
                if name:
                    valid.add(name)

    if not valid:
        sys.exit("Could not find Property EntityType in $metadata")

    print(f"Valid Property fields in AMPRE schema: {len(valid)}")
    print()

    requested = list(SELECT_FIELDS)
    bad = [f for f in requested if f not in valid]
    good = [f for f in requested if f in valid]

    print(f"SELECT_FIELDS passes: {len(good)} / {len(requested)}")
    print()

    if bad:
        print(f"REMOVE from SELECT_FIELDS ({len(bad)} field(s)):")
        for f in bad:
            print(f"  {f!r}")
        print()
        print("Suggested replacements (searching schema by substring):")
        for f in bad:
            substrs = [s for s in valid if f.lower()[:6] in s.lower()]
            if substrs:
                print(f"  {f} -> candidates: {substrs[:5]}")
    else:
        print("All SELECT_FIELDS are valid. The 400 must be from the $filter.")


if __name__ == "__main__":
    main()
