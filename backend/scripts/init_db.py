from pathlib import Path
import sys

import psycopg

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings


def ensure_application_role(cursor) -> None:
    app_role = settings.database_app_role.strip()
    if not app_role:
        return

    cursor.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{app_role}') THEN
                CREATE ROLE "{app_role}" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
            END IF;
        END
        $$;
        """
    )
    cursor.execute(f'GRANT USAGE ON SCHEMA public TO "{app_role}";')
    cursor.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public TO "{app_role}";')
    cursor.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{app_role}";')
    cursor.execute(f'GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO "{app_role}";')
    cursor.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLES TO "{app_role}";')
    cursor.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO "{app_role}";')
    cursor.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO "{app_role}";')


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
            ensure_application_role(cursor)

    print(f"Applied {len(migration_files)} migration(s)")


if __name__ == "__main__":
    main()
