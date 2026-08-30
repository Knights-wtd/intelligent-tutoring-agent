import os
from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from sqlalchemy import engine_from_config, pool

import tutor_api.agent.models  # noqa: F401
import tutor_api.billing.models  # noqa: F401
import tutor_api.classrooms.models  # noqa: F401
import tutor_api.identity.models  # noqa: F401
import tutor_api.knowledge.models  # noqa: F401
import tutor_api.providers.models  # noqa: F401
import tutor_api.question_bank.models  # noqa: F401
import tutor_api.spaces.models  # noqa: F401
import tutor_api.tutor.models  # noqa: F401
import tutor_api.vault.models  # noqa: F401
from tutor_api.core.database import Base

config = context.config

database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_TASK7_SHORT_REVISION = "0003_reservation_provider"
_TASK7_HISTORICAL_REVISION = "0003_bind_reservations_to_provider"


def _bridge_short_lived_task7_revision(connection: sa.Connection) -> None:
    """Map the briefly-published Task 7 revision id back to its preserved history."""

    inspector = sa.inspect(connection)
    if "alembic_version" not in inspector.get_table_names():
        return
    version = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
    if version != _TASK7_SHORT_REVISION:
        return
    if connection.dialect.name == "postgresql":
        connection.execute(
            sa.text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)")
        )
    connection.execute(
        sa.text(
            "UPDATE alembic_version SET version_num = :historical_revision "
            "WHERE version_num = :short_revision"
        ),
        {
            "historical_revision": _TASK7_HISTORICAL_REVISION,
            "short_revision": _TASK7_SHORT_REVISION,
        },
    )


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            _bridge_short_lived_task7_revision(connection)
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
