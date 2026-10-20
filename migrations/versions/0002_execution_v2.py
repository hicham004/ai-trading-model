"""execution v2: exchange-side protective stops, entry-policy quality fields

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-20

Additive only: a new ``demo_algo_orders`` table (the exchange-side protective
stop ledger), execution-quality columns on ``demo_order_intents`` and the
``stop_alarm`` column on ``demo_runtime_status``. Nothing is dropped; the
downgrade removes exactly what this revision added.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('demo_algo_orders',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('account_id', sa.Integer(), nullable=False),
    sa.Column('algo_cl_ord_id', sa.String(length=32), nullable=False),
    sa.Column('algo_id', sa.String(length=64), nullable=True),
    sa.Column('instrument', sa.String(length=32), nullable=False),
    sa.Column('parent_client_order_id', sa.String(length=32), nullable=True),
    sa.Column('side', sa.String(length=4), nullable=False),
    sa.Column('ord_type', sa.String(length=12), nullable=False),
    sa.Column('size', sa.String(length=40), nullable=False),
    sa.Column('trigger_price', sa.String(length=40), nullable=False),
    sa.Column('order_price', sa.String(length=40), nullable=False),
    sa.Column('tp_trigger_price', sa.String(length=40), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('child_order_id', sa.String(length=64), nullable=True),
    sa.Column('child_client_order_id', sa.String(length=32), nullable=True),
    sa.Column('actual_size', sa.String(length=40), nullable=True),
    sa.Column('actual_price', sa.String(length=40), nullable=True),
    sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('triggered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_update_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.String(length=256), nullable=True),
    sa.ForeignKeyConstraint(['account_id'], ['demo_accounts.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('account_id', 'algo_cl_ord_id', name='uq_demo_algo_clordid')
    )
    with op.batch_alter_table('demo_algo_orders', schema=None) as batch_op:
        batch_op.create_index('ix_demo_algo_status', ['account_id', 'status'], unique=False)
        batch_op.create_index(batch_op.f('ix_demo_algo_orders_account_id'), ['account_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_demo_algo_orders_algo_cl_ord_id'), ['algo_cl_ord_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_demo_algo_orders_algo_id'), ['algo_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_demo_algo_orders_child_order_id'), ['child_order_id'], unique=False)

    with op.batch_alter_table('demo_order_intents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('entry_policy', sa.String(length=24), nullable=True))
        batch_op.add_column(sa.Column('reference_price', sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column('expected_slippage_bps', sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column('realized_slippage_bps', sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column('parent_client_order_id', sa.String(length=32), nullable=True))

    with op.batch_alter_table('demo_runtime_status', schema=None) as batch_op:
        batch_op.add_column(sa.Column('stop_alarm', sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('demo_runtime_status', schema=None) as batch_op:
        batch_op.drop_column('stop_alarm')

    with op.batch_alter_table('demo_order_intents', schema=None) as batch_op:
        batch_op.drop_column('parent_client_order_id')
        batch_op.drop_column('realized_slippage_bps')
        batch_op.drop_column('expected_slippage_bps')
        batch_op.drop_column('reference_price')
        batch_op.drop_column('entry_policy')

    with op.batch_alter_table('demo_algo_orders', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_demo_algo_orders_child_order_id'))
        batch_op.drop_index(batch_op.f('ix_demo_algo_orders_algo_id'))
        batch_op.drop_index(batch_op.f('ix_demo_algo_orders_algo_cl_ord_id'))
        batch_op.drop_index(batch_op.f('ix_demo_algo_orders_account_id'))
        batch_op.drop_index('ix_demo_algo_status')

    op.drop_table('demo_algo_orders')
