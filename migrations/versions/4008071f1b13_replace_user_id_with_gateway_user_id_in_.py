"""replace user_id with gateway_user_id in responsible_persons

Revision ID: 4008071f1b13
Revises: 55111865ab5f
Create Date: 2025-10-23 15:09:34.964664

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4008071f1b13'
down_revision = '55111865ab5f'
branch_labels = None
depends_on = None


def upgrade():
    # Для SQLite используем batch mode с явным пересозданием таблицы
    with op.batch_alter_table('responsible_persons', schema=None) as batch_op:
        # Добавляем новую колонку
        batch_op.add_column(sa.Column('gateway_user_id', sa.String(length=24), nullable=True))
        batch_op.create_index(batch_op.f('ix_responsible_persons_gateway_user_id'), ['gateway_user_id'], unique=True)
        
        # Для SQLite: просто удаляем старую колонку (FK удалится автоматически при пересоздании таблицы)
        batch_op.drop_column('user_id')


def downgrade():
    with op.batch_alter_table('responsible_persons', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.INTEGER(), nullable=True))
        batch_op.drop_index(batch_op.f('ix_responsible_persons_gateway_user_id'))
        batch_op.drop_column('gateway_user_id')
