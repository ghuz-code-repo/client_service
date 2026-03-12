"""Remove password_hash column - auth via Gateway

Revision ID: 55111865ab5f
Revises: 48a64ea6cb7c
Create Date: 2025-10-21 15:31:03.020551

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '55111865ab5f'
down_revision = '48a64ea6cb7c'
branch_labels = None
depends_on = None


def upgrade():
    """
    Удаляем поле password_hash из таблицы users.
    Аутентификация теперь полностью осуществляется через Gateway.
    """
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('password_hash')


def downgrade():
    """
    Восстанавливаем поле password_hash (на случай отката).
    """
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('password_hash', sa.String(length=256), nullable=True))
