"""Durable, content-free refresh run and source events.

Revision ID: 0013
Revises: 0012
"""
from alembic import op

from sci_rag.db.models import FileEvent

revision='0013'
down_revision='0012'
branch_labels=None
depends_on=None


def upgrade() -> None:
    FileEvent.__table__.create(op.get_bind(),checkfirst=True)


def downgrade() -> None:
    FileEvent.__table__.drop(op.get_bind(),checkfirst=True)
