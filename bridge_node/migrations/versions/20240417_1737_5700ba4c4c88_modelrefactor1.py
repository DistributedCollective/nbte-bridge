"""modelrefactor1

Revision ID: 5700ba4c4c88
Revises: deb62cf78dee
Create Date: 2024-04-17 17:37:34.559504

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '5700ba4c4c88'
down_revision = 'deb62cf78dee'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('runes_deposit_address')
    op.drop_table('runes_user')
    op.create_table('bridge',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bridge')),
    sa.UniqueConstraint('name', name=op.f('uq_bridge_name'))
    )
    op.create_table('user',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('bridge_id', sa.Integer(), nullable=False),
    sa.Column('evm_address', sa.LargeBinary, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['bridge_id'], ['bridge.id'], name=op.f('fk_user_bridge_id_bridge')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user')),
    sa.UniqueConstraint('bridge_id', 'evm_address', name='uq_runes_user_evm_address')
    )
    op.create_index(op.f('ix_user_evm_address'), 'user', ['evm_address'], unique=False)
    op.create_table('deposit_address',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('btc_address', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], name=op.f('fk_deposit_address_user_id_user')),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_deposit_address')),
    sa.UniqueConstraint('btc_address', name=op.f('uq_deposit_address_btc_address'))
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('deposit_address')
    op.drop_index(op.f('ix_user_evm_address'), table_name='user')
    op.drop_table('user')
    op.drop_table('bridge')
    op.create_table('runes_user',
    sa.Column('id', sa.INTEGER(), server_default=sa.text("nextval('runes_user_id_seq'::regclass)"), autoincrement=True, nullable=False),
    sa.Column('bridge_id', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('evm_address', postgresql.BYTEA(), autoincrement=False, nullable=False),
    sa.PrimaryKeyConstraint('id', name='pk_runes_user'),
    sa.UniqueConstraint('bridge_id', 'evm_address', name='uq_runes_user_evm_address'),
    postgresql_ignore_search_path=False
    )
    op.create_table('runes_deposit_address',
    sa.Column('user_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('btc_address', sa.TEXT(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['runes_user.id'], name='fk_runes_deposit_address_user_id_runes_user'),
    sa.PrimaryKeyConstraint('user_id', name='pk_runes_deposit_address'),
    sa.UniqueConstraint('btc_address', name='uq_runes_deposit_address_btc_address')
    )
    # ### end Alembic commands ###
