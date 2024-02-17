"""tap-rsk-models

Revision ID: 2fa523364d25
Revises: 0b9b8d327b29
Create Date: 2024-02-17 22:54:31.025952

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '2fa523364d25'
down_revision = '0b9b8d327b29'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('taprsk_bridgeable_asset',
    sa.Column('db_id', sa.Integer(), nullable=False),
    sa.Column('rsk_token_address', sa.Text(), nullable=False),
    sa.Column('tap_asset_id', sa.Text(), nullable=False),
    sa.Column('tap_amount_divisor', sa.Integer(), nullable=False),
    sa.Column('tap_asset_name', sa.Text(), nullable=False),
    sa.Column('rsk_event_block_number', sa.Integer(), nullable=False),
    sa.Column('rsk_event_tx_hash', sa.Text(), nullable=False),
    sa.Column('rsk_event_tx_index', sa.Integer(), nullable=False),
    sa.Column('rsk_event_log_index', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('db_id', name=op.f('pk_taprsk_bridgeable_asset'))
    )
    op.create_table('taprsk_rsk_to_tap_transfer_batch',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('status', sa.Integer(), nullable=False),
    sa.Column('sending_result', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_taprsk_rsk_to_tap_transfer_batch'))
    )
    op.create_table('taprsk_tap_deposit_address',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('rsk_address', sa.Text(), nullable=False),
    sa.Column('tap_address', sa.Text(), nullable=False),
    sa.Column('tap_asset_id', sa.Text(), nullable=False),
    sa.Column('rsk_token_address', sa.Text(), nullable=False),
    sa.Column('tap_amount', sa.Text(), nullable=False),
    sa.Column('rsk_amount', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_taprsk_tap_deposit_address')),
    sa.UniqueConstraint('tap_address', name=op.f('uq_taprsk_tap_deposit_address_tap_address'))
    )
    op.create_table('taprsk_tap_to_rsk_transfer_batch',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('hash', sa.LargeBinary(length=32), nullable=False),
    sa.Column('status', sa.Integer(), nullable=False),
    sa.Column('signatures', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('executed_tx_hash', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_taprsk_tap_to_rsk_transfer_batch')),
    sa.UniqueConstraint('hash', name=op.f('uq_taprsk_tap_to_rsk_transfer_batch_hash'))
    )
    op.create_table('taprsk_rsk_to_tap_transfer',
    sa.Column('db_id', sa.Integer(), nullable=False),
    sa.Column('counter', sa.Integer(), nullable=False),
    sa.Column('recipient_tap_address', sa.Text(), nullable=False),
    sa.Column('rsk_event_block_number', sa.Integer(), nullable=False),
    sa.Column('rsk_event_tx_hash', sa.Text(), nullable=False),
    sa.Column('rsk_event_tx_index', sa.Integer(), nullable=False),
    sa.Column('rsk_event_log_index', sa.Integer(), nullable=False),
    sa.Column('transfer_batch_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['transfer_batch_id'], ['taprsk_rsk_to_tap_transfer_batch.id'], name=op.f('fk_taprsk_rsk_to_tap_transfer_transfer_batch_id_taprsk_rsk_to_tap_transfer_batch')),
    sa.PrimaryKeyConstraint('db_id', name=op.f('pk_taprsk_rsk_to_tap_transfer')),
    sa.UniqueConstraint('counter', name=op.f('uq_taprsk_rsk_to_tap_transfer_counter')),
    sa.UniqueConstraint('rsk_event_tx_hash', 'rsk_event_tx_index', 'rsk_event_log_index', name='uq_taprsk_rsk_to_tap_transfer_event')
    )
    op.create_index(op.f('ix_taprsk_rsk_to_tap_transfer_transfer_batch_id'), 'taprsk_rsk_to_tap_transfer', ['transfer_batch_id'], unique=False)
    op.create_table('taprsk_tap_to_rsk_transfer',
    sa.Column('db_id', sa.Integer(), nullable=False),
    sa.Column('counter', sa.Integer(), nullable=True),
    sa.Column('deposit_address_id', sa.Integer(), nullable=False),
    sa.Column('deposit_btc_tx_id', sa.Text(), nullable=False),
    sa.Column('deposit_btc_tx_vout', sa.Integer(), nullable=False),
    sa.Column('transfer_batch_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['deposit_address_id'], ['taprsk_tap_deposit_address.id'], name=op.f('fk_taprsk_tap_to_rsk_transfer_deposit_address_id_taprsk_tap_deposit_address')),
    sa.ForeignKeyConstraint(['transfer_batch_id'], ['taprsk_tap_to_rsk_transfer_batch.id'], name=op.f('fk_taprsk_tap_to_rsk_transfer_transfer_batch_id_taprsk_tap_to_rsk_transfer_batch')),
    sa.PrimaryKeyConstraint('db_id', name=op.f('pk_taprsk_tap_to_rsk_transfer')),
    sa.UniqueConstraint('counter', name=op.f('uq_taprsk_tap_to_rsk_transfer_counter')),
    sa.UniqueConstraint('deposit_btc_tx_id', 'deposit_btc_tx_vout', name='uq_taprsk_tap_to_rsk_transfer_txid_vout')
    )
    op.create_index(op.f('ix_taprsk_tap_to_rsk_transfer_transfer_batch_id'), 'taprsk_tap_to_rsk_transfer', ['transfer_batch_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_taprsk_tap_to_rsk_transfer_transfer_batch_id'), table_name='taprsk_tap_to_rsk_transfer')
    op.drop_table('taprsk_tap_to_rsk_transfer')
    op.drop_index(op.f('ix_taprsk_rsk_to_tap_transfer_transfer_batch_id'), table_name='taprsk_rsk_to_tap_transfer')
    op.drop_table('taprsk_rsk_to_tap_transfer')
    op.drop_table('taprsk_tap_to_rsk_transfer_batch')
    op.drop_table('taprsk_tap_deposit_address')
    op.drop_table('taprsk_rsk_to_tap_transfer_batch')
    op.drop_table('taprsk_bridgeable_asset')
