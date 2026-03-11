import uuid as _uuid
import os

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.types import TypeDecorator, String

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv opcional; use variáveis de ambiente do sistema


# ─── Tipo GUID universal (PostgreSQL nativo / SQLite como String) ─────────────

class GUID(TypeDecorator):
    """
    UUID portável: usa UUID nativo no PostgreSQL, String(36) nos demais
    (SQLite, etc.). Sempre retorna objetos uuid.UUID no Python.
    """
    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID as PG_UUID
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, _uuid.UUID):
            return value if dialect.name == "postgresql" else str(value)
        return _uuid.UUID(str(value)) if dialect.name == "postgresql" else str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return value if isinstance(value, _uuid.UUID) else _uuid.UUID(str(value))


# ─── Conexão ──────────────────────────────────────────────────────────────────

# Padrão: SQLite local (sem instalação). Para produção, defina DATABASE_URL
# com a string do PostgreSQL no arquivo .env
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./smartfood.db"
)

connect_args = {"check_same_thread": False} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
