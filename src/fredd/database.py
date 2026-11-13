from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from fredd.config import settings


class Base(DeclarativeBase):
    # Stable constraint names keep Alembic autogenerate diffs predictable.
    metadata = MetaData(
        naming_convention={
            "ix": "%(column_0_label)s_idx",
            "uq": "%(table_name)s_%(column_0_name)s_key",
            "ck": "%(table_name)s_%(constraint_name)s_check",
            "fk": "%(table_name)s_%(column_0_name)s_fkey",
            "pk": "%(table_name)s_pkey",
        }
    )


engine = create_async_engine(settings.database_url, pool_pre_ping=True, connect_args={"timeout": 5})
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
