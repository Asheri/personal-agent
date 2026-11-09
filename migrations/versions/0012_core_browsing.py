"""Document dates, access counters, and universal identifier backfill.

Revision ID: 0012
Revises: 0011
"""
import sqlalchemy as sa
from alembic import op

from sci_rag.document_dates import document_date
from sci_rag.keyword_tokens import index_chinese, index_search

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind=op.get_bind()
    # Earlier migration steps can queue deferred version-FK events in this same
    # transaction. Validate them before ALTER TABLE and restore deferral afterward.
    op.execute('SET CONSTRAINTS ALL IMMEDIATE')
    columns={column['name'] for column in sa.inspect(bind).get_columns('documents')}
    additions=[sa.Column('doc_date',sa.Date()),sa.Column('doc_date_source',sa.Text()),sa.Column('access_count',sa.Integer(),nullable=False,server_default='0'),sa.Column('last_accessed_at',sa.DateTime(timezone=True))]
    for column in additions:
        if column.name not in columns:
            op.add_column('documents',column)
    constraints={row['name'] for row in sa.inspect(bind).get_check_constraints('documents')}
    for name,sql in [('ck_documents_access_count','access_count >= 0'),('ck_documents_doc_date_source',"doc_date_source IS NULL OR doc_date_source IN ('email_header','doc_property','file_mtime','ingested_at')")]:
        if name not in constraints:
            op.create_check_constraint(name,'documents',sql)
    indexes={row['name'] for row in sa.inspect(bind).get_indexes('documents')}
    for name,column in [('ix_documents_doc_date','doc_date'),('ix_documents_last_accessed_at','last_accessed_at')]:
        if name not in indexes:
            op.create_index(name,'documents',[column])
    last=''
    while rows:=bind.execute(sa.text('SELECT id,extra,ingested_at FROM documents WHERE id>:last ORDER BY id LIMIT 500'),{'last':last}).mappings().all():
        values=[]
        for row in rows:
            metadata=row['extra'] or {}
            when,source=document_date(metadata,metadata.get('source_fingerprint',{}).get('mtime_ns'),row['ingested_at'])
            values.append(dict(id=row['id'],day=when,source=source))
        bind.execute(sa.text('UPDATE documents SET doc_date=:day,doc_date_source=:source WHERE id=:id'),values)
        last=rows[-1]['id']
    _backfill(index_search)
    op.execute('SET CONSTRAINTS ALL DEFERRED')


def _backfill(indexer):
    bind=op.get_bind()
    last=''
    while rows:=bind.execute(sa.text('SELECT id,content FROM chunks WHERE id>:last ORDER BY id LIMIT 500'),{'last':last}).all():
        bind.execute(sa.text('UPDATE chunks SET search_tokens=:tokens WHERE id=:id'),[dict(id=row.id,tokens=indexer(row.content)) for row in rows])
        last=rows[-1].id


def downgrade() -> None:
    op.execute('SET CONSTRAINTS ALL IMMEDIATE')
    _backfill(index_chinese)
    for index in ['ix_documents_last_accessed_at','ix_documents_doc_date']:
        op.drop_index(index,table_name='documents')
    for constraint in ['ck_documents_access_count','ck_documents_doc_date_source']:
        op.drop_constraint(constraint,'documents',type_='check')
    for column in ['last_accessed_at','access_count','doc_date_source','doc_date']:
        op.drop_column('documents',column)
    op.execute('SET CONSTRAINTS ALL DEFERRED')
