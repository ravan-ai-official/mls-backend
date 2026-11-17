"""
Local dry-run launcher for sync_ampre_closed / sync_ddf_properties.

Loads .env.prod for AMPRE/DDF credentials, overrides DATABASE_URL to a
local scratch SQLite file, then forwards remaining argv to manage.py.

Usage:
    python scripts/dry_run.py sync_ampre_closed --dry-run
    python scripts/dry_run.py sync_ddf_properties --dry-run

Writes NOTHING to the prod DB — only to ./dry_run_scratch.db locally.
"""
import os
import sys
from pathlib import Path

from dotenv import dotenv_values


def main() -> None:
    repo = Path(__file__).resolve().parent.parent
    env_prod = repo / ".env.prod"
    if not env_prod.exists():
        sys.exit(f"Missing {env_prod}")

    # Load real prod env (AMPRE token, DDF creds, SECRET_KEY, etc.)
    for k, v in dotenv_values(env_prod).items():
        if v is not None:
            os.environ[k] = v

    # Override DB to a scratch SQLite file — guarantees no prod DB writes
    # even if a command accidentally tries to save. Also forces DEBUG off
    # so misconfig doesn't leak traces.
    scratch = repo / "dry_run_scratch.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{scratch}"
    os.environ.setdefault("DEBUG", "False")
    os.environ.setdefault("ALLOWED_HOSTS", "localhost,127.0.0.1")

    print(f"[dry_run] DATABASE_URL -> sqlite:///{scratch}")
    print(f"[dry_run] forwarding to manage.py: {sys.argv[1:]}")
    print()

    # Delegate to Django manage.py in-process so argv parsing matches
    sys.path.insert(0, str(repo))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line([str(repo / "manage.py"), *sys.argv[1:]])


if __name__ == "__main__":
    main()
