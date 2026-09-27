"""
Alembic environment — pulls the DB URL from app.core.config (so you never
maintain the connection string twice) and Base.metadata from app.models
(so `alembic revision --autogenerate` sees every table).
"""
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.db import Base  # noqa: E402
import app.models  # noqa: E402,F401 — import triggers model registration onto Base.metadata

config = context.config
config.set_main_option("sqlalchemy.url", settings.sqlalchemy_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# PostGIS creates its own internal bookkeeping tables (spatial_ref_sys and,
# depending on version, a few others) directly in the database — they're
# not part of our models and never will be. Without this filter,
# `alembic revision --autogenerate` sees them as "extra" tables not in
# Base.metadata and generates a migration that DROPS them, which breaks
# PostGIS the first time anyone actually runs `alembic upgrade head`.
POSTGIS_SYSTEM_TABLES = {"spatial_ref_sys"}


def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table" and name in POSTGIS_SYSTEM_TABLES:
        return False
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True,
        dialect_opts={"paramstyle": "named"}, include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
