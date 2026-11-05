"""The projects registry: one row per thread, so that a person's projects can be listed

The checkpointer holds each thread's state and history; this holds only what a listing needs, never a run's progress.
`owner` is the sign-in id, null until there is sign-in.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE projects (
            thread_id TEXT PRIMARY KEY,
            owner TEXT,
            title TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX projects_owner_updated_at ON projects (owner, updated_at DESC)")  # a person's projects, newest first


def downgrade() -> None:
    op.execute("DROP TABLE projects")
