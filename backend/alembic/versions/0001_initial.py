"""Create instrument, bar, and task history tables.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_instruments() -> None:
    op.create_table(
        "instruments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("market", sa.String(length=32), nullable=False),
        sa.Column("exchange", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("instrument_type", sa.String(length=32), nullable=False),
        sa.Column("provider_symbol", sa.String(length=256), nullable=False),
        sa.Column(
            "active", sa.Boolean(), server_default=sa.text("1"), nullable=False
        ),
        sa.CheckConstraint(
            "instrument_type IN ('stock', 'index', 'etf', 'crypto_spot')",
            name="ck_instruments_valid_instrument_type",
        ),
        sa.CheckConstraint(
            "market IN ('a_share', 'hk_stock', 'us_stock', 'crypto')",
            name="ck_instruments_valid_market",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_instruments"),
        sa.UniqueConstraint(
            "market", "symbol", name="uq_instruments_market_symbol"
        ),
    )
    op.create_index(
        "ix_instruments_market_active",
        "instruments",
        ["market", "active"],
        unique=False,
    )
    op.create_index("ix_instruments_name", "instruments", ["name"], unique=False)


def _create_universe_memberships() -> None:
    op.create_table(
        "universe_memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("universe_code", sa.String(length=128), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_universe_memberships_instrument_id_instruments",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_universe_memberships"),
        sa.UniqueConstraint(
            "universe_code",
            "instrument_id",
            name="uq_universe_memberships_universe_instrument",
        ),
    )
    op.create_index(
        "ix_universe_memberships_instrument_id",
        "universe_memberships",
        ["instrument_id"],
        unique=False,
    )

def _create_daily_bars() -> None:
    op.create_table(
        "daily_bars",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("adjustment", sa.String(length=16), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "adjustment IN ('qfq', 'none')",
            name="ck_daily_bars_valid_adjustment",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_daily_bars_instrument_id_instruments",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_daily_bars"),
        sa.UniqueConstraint(
            "instrument_id", "date", name="uq_daily_bars_instrument_date"
        ),
    )
    op.create_index("ix_daily_bars_date", "daily_bars", ["date"], unique=False)

def _create_task_runs() -> None:
    op.create_table(
        "task_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_name", sa.String(length=256), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="queued", nullable=False
        ),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("config_snapshot", sa.JSON(), nullable=True),
        sa.Column("progress", sa.Float(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "progress >= 0 AND progress <= 100",
            name="ck_task_runs_valid_progress",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'success', 'partial', 'failed', "
            "'skipped', 'interrupted')",
            name="ck_task_runs_valid_status",
        ),
        sa.CheckConstraint(
            "trigger IN ('manual', 'scheduled')",
            name="ck_task_runs_valid_trigger",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_task_runs"),
    )
    _create_task_run_indexes()


def _create_task_run_indexes() -> None:
    op.create_index(
        "ix_task_runs_created_at", "task_runs", ["created_at"], unique=False
    )
    op.create_index(
        "ix_task_runs_task_name_id",
        "task_runs",
        ["task_name", "id"],
        unique=False,
    )

def _create_task_logs() -> None:
    op.create_table(
        "task_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["task_runs.id"],
            name="fk_task_logs_run_id_task_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_task_logs"),
    )
    op.create_index(
        "ix_task_logs_run_id_id", "task_logs", ["run_id", "id"], unique=False
    )


def upgrade() -> None:
    """Create the complete initial schema."""
    _create_instruments()
    _create_universe_memberships()
    _create_daily_bars()
    _create_task_runs()
    _create_task_logs()


def downgrade() -> None:
    """Drop all initial tables in dependency order."""
    op.drop_index("ix_task_logs_run_id_id", table_name="task_logs")
    op.drop_table("task_logs")
    op.drop_index("ix_task_runs_task_name_id", table_name="task_runs")
    op.drop_index("ix_task_runs_created_at", table_name="task_runs")
    op.drop_table("task_runs")
    op.drop_index("ix_daily_bars_date", table_name="daily_bars")
    op.drop_table("daily_bars")
    op.drop_index(
        "ix_universe_memberships_instrument_id",
        table_name="universe_memberships",
    )
    op.drop_table("universe_memberships")
    op.drop_index("ix_instruments_name", table_name="instruments")
    op.drop_index("ix_instruments_market_active", table_name="instruments")
    op.drop_table("instruments")
