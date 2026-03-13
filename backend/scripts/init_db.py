from pathlib import Path
import sys

import psycopg

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings


def main() -> None:
    migrations_dir = BACKEND_DIR / "migrations"
    migration_files = sorted(migrations_dir.glob("*.sql"))
    if not migration_files:
        raise RuntimeError("No migration files found")

    with psycopg.connect(settings.psycopg_database_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            for migration_path in migration_files:
                sql = migration_path.read_text(encoding="utf-8").replace(
                    "__EMBED_DIMENSIONS__", str(settings.llm_embed_dimensions)
                )
                cursor.execute(sql)

    print(f"Applied {len(migration_files)} migration(s)")


if __name__ == "__main__":
    main()
