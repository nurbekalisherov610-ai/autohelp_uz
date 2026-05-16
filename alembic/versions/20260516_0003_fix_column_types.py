"""fix column types and sla watchdog

Revision ID: 20260516_0003
Revises: 20260516_0002
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260516_0003"
down_revision: str | None = "20260516_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Fix 'language' column type mismatch. 
    # If it's a custom enum type, convert it to VARCHAR.
    # We use a TRY...EXCEPT block-like logic via SQL to handle cases where it's already VARCHAR.
    op.execute("""
        DO $$ 
        BEGIN 
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'users' 
                AND column_name = 'language' 
                AND data_type = 'USER-DEFINED'
            ) THEN
                ALTER TABLE users ALTER COLUMN language TYPE VARCHAR(10) USING language::text;
            END IF;
        END $$;
    """)

    # 2. Ensure orders table columns have correct types if they were created as native enums
    op.execute("""
        DO $$ 
        BEGIN 
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'orders' 
                AND column_name = 'status' 
                AND data_type = 'USER-DEFINED'
            ) THEN
                ALTER TABLE orders ALTER COLUMN status TYPE VARCHAR(32) USING status::text;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    # No easy way to restore custom types without knowing their names, 
    # and VARCHAR is more flexible anyway.
    pass
