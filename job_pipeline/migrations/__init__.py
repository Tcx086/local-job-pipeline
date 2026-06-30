from __future__ import annotations

import argparse
from pathlib import Path

from ..company_registry import load_company_registry
from ..database import DEFAULT_DB, connect, upsert_companies


def migrate(db_path: Path = DEFAULT_DB) -> None:
    conn = connect(db_path)
    try:
        upsert_companies(conn, load_company_registry())
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize or update the job_pipeline SQLite schema.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    migrate(args.db)
    print(f"Migrated {args.db}")
    return 0
