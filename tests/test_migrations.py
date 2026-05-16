import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parents[1]


def _load_module(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load migration module from {relative_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_upgrade(module_name: str, relative_path: str, connection: sa.Connection) -> None:
    module = _load_module(module_name, relative_path)
    operations = Operations(MigrationContext.configure(connection))
    original_op = module.op
    module.op = operations
    try:
        module.upgrade()
    finally:
        module.op = original_op


def test_migrations_heal_legacy_partial_schema() -> None:
    engine = sa.create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    telegram_id BIGINT NOT NULL,
                    full_name VARCHAR(255),
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                CREATE TABLE orders (
                    id INTEGER PRIMARY KEY,
                    client_id INTEGER NOT NULL,
                    issue_type VARCHAR(32) NOT NULL,
                    issue_label VARCHAR(100) NOT NULL,
                    phone VARCHAR(32) NOT NULL,
                    latitude FLOAT NOT NULL,
                    longitude FLOAT NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO users (id, telegram_id, full_name)
                VALUES (:id, :telegram_id, :full_name)
                """
            ),
            {"id": 1, "telegram_id": 998901234567, "full_name": "Legacy Driver"},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO orders (
                    id, client_id, issue_type, issue_label, phone, latitude, longitude, status
                ) VALUES (
                    :id, :client_id, :issue_type, :issue_label, :phone, :latitude, :longitude, :status
                )
                """
            ),
            {
                "id": 1,
                "client_id": 1,
                "issue_type": "BATTERY_DOWN",
                "issue_label": "Akkumulyator o'tirgan",
                "phone": "+998901234567",
                "latitude": 41.3,
                "longitude": 69.2,
                "status": "NEW",
            },
        )

        _run_upgrade(
            "migration_20260418_0001",
            "alembic/versions/20260418_0001_initial_schema.py",
            connection,
        )
        _run_upgrade(
            "migration_20260516_0002",
            "alembic/versions/20260516_0002_add_operational_bot_columns.py",
            connection,
        )

        inspector = sa.inspect(connection)
        order_columns = {column["name"] for column in inspector.get_columns("orders")}
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        order_indexes = {index["name"] for index in inspector.get_indexes("orders")}

        assert "assigned_dispatcher_telegram_id" in order_columns
        assert "assigned_master_telegram_id" in order_columns
        assert "final_amount" in order_columns
        assert "completed_at" in order_columns
        assert "video_file_id" in order_columns
        assert "rating" in order_columns
        assert "phone" in user_columns
        assert "language" in user_columns
        assert "is_master" in user_columns
        assert "ix_orders_status" in order_indexes
        assert "ix_orders_assigned_master_telegram_id" in order_indexes

        legacy_row = connection.execute(
            sa.text(
                """
                SELECT assigned_master_telegram_id, video_file_id, rating
                FROM orders
                WHERE id = 1
                """
            )
        ).one()
        assert tuple(legacy_row) == (None, None, None)
