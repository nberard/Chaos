"""add table channel_type

Revision ID: 11f1722d941f
Revises: 22ced1088b04
Create Date: 2015-06-22 09:55:39.004203

"""

# revision identifiers, used by Alembic.
revision = '11f1722d941f'
down_revision = '22ced1088b04'

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid
from datetime import datetime

channel_type_enum = sa.Enum('web', 'sms', 'email', 'mobile', 'notification', 'twitter', 'facebook', name='channel_type_enum')

def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    channel_type_enum.create(op.get_bind(), True)
    op.create_table('channel_type',
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.Column('id', postgresql.UUID(), nullable=False),
    sa.Column('channel_id', postgresql.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['channel_id'], [u'channel.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.add_column('channel_type', sa.Column('name', channel_type_enum, nullable=False, server_default='web', index=True))
    op.create_index('ix_channel_type_name', 'channel_type', ['name'], unique=False)
    connection = op.get_bind()

    result = connection.execute('select id from channel')
    for row in result:
        for type in channel_type_enum.enums:
            op.execute("INSERT INTO channel_type (created_at, id, channel_id, name) VALUES ('{}','{}', '{}','{}')".
                       format(datetime.utcnow(), str(uuid.uuid1()), row['id'], type))
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('ix_channel_type_name', 'channel_type')
    op.drop_table('channel_type')
    channel_type_enum.drop(op.get_bind())
    ### end Alembic commands ###
