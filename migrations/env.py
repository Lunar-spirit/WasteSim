import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.core.db import Base

# Import every model module so Base.metadata is fully populated for
# autogenerate; each import is required even though nothing is referenced.
from app.auth import models as _auth_models  # noqa: F401
from app.audit import models as _audit_models  # noqa: F401
from app.habitation import models as _habitation_models  # noqa: F401
from app.parameters import models as _parameters_models  # noqa: F401
from app.validation import models as _validation_models  # noqa: F401
from app.gis import models as _gis_models  # noqa: F401
from app.ingestion import models as _ingestion_models  # noqa: F401
from app.simulation import models as _simulation_models  # noqa: F401
from app.budget import models as _budget_models  # noqa: F401
from app.optimization import models as _optimization_models  # noqa: F401
from app.scenario import models as _scenario_models  # noqa: F401
from app.sensitivity import models as _sensitivity_models  # noqa: F401
from app.comparison import models as _comparison_models  # noqa: F401
from app.reports import models as _reports_models  # noqa: F401
from app.chat import models as _chat_models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
