from collections.abc import Generator
import re

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


RLS_USER_ID_KEY = "rls_user_id"
AUTH_BYPASS_KEY = "auth_bypass"
SAFE_ROLE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


@event.listens_for(engine, "checkout")
def apply_application_role(dbapi_connection, connection_record, connection_proxy) -> None:
    app_role = settings.database_app_role.strip()
    if not app_role:
        return
    if not SAFE_ROLE_PATTERN.fullmatch(app_role):
        raise ValueError(f"Invalid database application role '{app_role}'")

    with dbapi_connection.cursor() as cursor:
        cursor.execute(f'SET ROLE "{app_role}"')


@event.listens_for(Session, "after_begin")
def apply_request_context(session: Session, transaction, connection) -> None:
    user_id = session.info.get(RLS_USER_ID_KEY)
    if user_id:
        connection.execute(
            text("SELECT set_config('app.current_user_id', :user_id, true)"),
            {"user_id": str(user_id)},
        )

    if session.info.get(AUTH_BYPASS_KEY):
        connection.execute(text("SELECT set_config('app.auth_bypass', 'true', true)"))


def bind_current_user_context(db: Session, user_id: str) -> None:
    db.info[RLS_USER_ID_KEY] = str(user_id)
    if db.in_transaction():
        db.execute(
            text("SELECT set_config('app.current_user_id', :user_id, true)"),
            {"user_id": str(user_id)},
        )


def enable_auth_bypass_context(db: Session) -> None:
    db.info[AUTH_BYPASS_KEY] = True
    if db.in_transaction():
        db.execute(text("SELECT set_config('app.auth_bypass', 'true', true)"))


def clear_request_context(db: Session) -> None:
    db.info.pop(RLS_USER_ID_KEY, None)
    db.info.pop(AUTH_BYPASS_KEY, None)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        clear_request_context(db)
        db.close()
