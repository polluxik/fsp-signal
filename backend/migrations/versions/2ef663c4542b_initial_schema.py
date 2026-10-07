"""initial schema

Revision ID: 2ef663c4542b
Revises: 
Create Date: 2026-10-05 10:46:14.114403

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2ef663c4542b'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('mail_outbox',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('recipient', sa.String(length=254), nullable=False),
    sa.Column('subject', sa.String(length=200), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_error', sa.String(length=200), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('users',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_table('assessment_attempts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('candidate_id', sa.String(length=36), nullable=False),
    sa.Column('specialization', sa.String(length=30), nullable=False),
    sa.Column('grade', sa.String(length=20), nullable=False),
    sa.Column('blueprint_version', sa.String(length=60), nullable=False),
    sa.Column('questions', sa.JSON(), nullable=False),
    sa.Column('answer_key', sa.JSON(), nullable=False),
    sa.Column('answers', sa.JSON(), nullable=False),
    sa.Column('phase', sa.Integer(), nullable=False),
    sa.Column('state', sa.String(length=20), nullable=False),
    sa.Column('score', sa.Integer(), nullable=True),
    sa.Column('outcome', sa.String(length=20), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['candidate_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_assessment_attempts_candidate_id'), 'assessment_attempts', ['candidate_id'], unique=False)
    op.create_table('candidate_profiles',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('full_name', sa.String(length=160), nullable=False),
    sa.Column('contact_email', sa.String(length=254), nullable=False),
    sa.Column('contact_phone', sa.String(length=80), nullable=False),
    sa.Column('city', sa.String(length=120), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('skills', sa.JSON(), nullable=False),
    sa.Column('experience_months', sa.Integer(), nullable=False),
    sa.Column('desired_specialization', sa.String(length=30), nullable=True),
    sa.Column('claimed_grade', sa.String(length=20), nullable=True),
    sa.Column('verified_specialization', sa.String(length=30), nullable=True),
    sa.Column('verified_grade', sa.String(length=20), nullable=True),
    sa.Column('test_score', sa.Integer(), nullable=True),
    sa.Column('verification_source', sa.String(length=30), nullable=True),
    sa.Column('competencies', sa.JSON(), nullable=False),
    sa.Column('test_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('grade_changed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('consent_processing_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('available', sa.Boolean(), nullable=False),
    sa.Column('min_salary_rub', sa.Integer(), nullable=False),
    sa.Column('work_format', sa.String(length=20), nullable=False),
    sa.Column('fsp_id', sa.String(length=80), nullable=True),
    sa.Column('fsp_status', sa.String(length=30), nullable=False),
    sa.Column('fsp_result', sa.String(length=40), nullable=True),
    sa.CheckConstraint('min_salary_rub >= 0', name='candidate_min_salary_nonnegative'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_index(op.f('ix_candidate_profiles_verified_grade'), 'candidate_profiles', ['verified_grade'], unique=False)
    op.create_index(op.f('ix_candidate_profiles_verified_specialization'), 'candidate_profiles', ['verified_specialization'], unique=False)
    op.create_table('email_tokens',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_email_tokens_user_id'), 'email_tokens', ['user_id'], unique=False)
    op.create_table('employer_profiles',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('company_name', sa.String(length=160), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('industry', sa.String(length=120), nullable=False),
    sa.Column('contact_email', sa.String(length=254), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('hiring_needs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('employer_id', sa.String(length=36), nullable=False),
    sa.Column('title', sa.String(length=180), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('specialization', sa.String(length=30), nullable=False),
    sa.Column('grade', sa.String(length=20), nullable=False),
    sa.Column('competencies', sa.JSON(), nullable=False),
    sa.Column('stack', sa.JSON(), nullable=False),
    sa.Column('salary_min_rub', sa.Integer(), nullable=False),
    sa.Column('salary_max_rub', sa.Integer(), nullable=False),
    sa.Column('work_format', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('salary_min_rub > 0 AND salary_max_rub >= salary_min_rub', name='need_salary_range'),
    sa.ForeignKeyConstraint(['employer_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_hiring_needs_employer_id'), 'hiring_needs', ['employer_id'], unique=False)
    op.create_table('login_sessions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_login_sessions_user_id'), 'login_sessions', ['user_id'], unique=False)
    op.create_table('invitations',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('employer_id', sa.String(length=36), nullable=False),
    sa.Column('candidate_id', sa.String(length=36), nullable=False),
    sa.Column('need_id', sa.String(length=36), nullable=True),
    sa.Column('company_name', sa.String(length=160), nullable=False),
    sa.Column('offer_text', sa.Text(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('employer_contact', sa.String(length=254), nullable=False),
    sa.Column('salary_min_rub', sa.Integer(), nullable=False),
    sa.Column('salary_max_rub', sa.Integer(), nullable=False),
    sa.Column('work_format', sa.String(length=20), nullable=False),
    sa.Column('state', sa.String(length=20), nullable=False),
    sa.Column('idempotency_key', sa.String(length=100), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('salary_min_rub > 0 AND salary_max_rub >= salary_min_rub', name='invitation_salary_range'),
    sa.ForeignKeyConstraint(['candidate_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['employer_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['need_id'], ['hiring_needs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('employer_id', 'idempotency_key', name='invitation_idempotency')
    )
    op.create_index(op.f('ix_invitations_candidate_id'), 'invitations', ['candidate_id'], unique=False)
    op.create_index(op.f('ix_invitations_employer_id'), 'invitations', ['employer_id'], unique=False)
    op.create_table('search_snapshots',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('employer_id', sa.String(length=36), nullable=False),
    sa.Column('need_id', sa.String(length=36), nullable=False),
    sa.Column('parent_id', sa.String(length=36), nullable=True),
    sa.Column('filters', sa.JSON(), nullable=False),
    sa.Column('results', sa.JSON(), nullable=False),
    sa.Column('algorithm_version', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['employer_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['need_id'], ['hiring_needs.id'], ),
    sa.ForeignKeyConstraint(['parent_id'], ['search_snapshots.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_search_snapshots_employer_id'), 'search_snapshots', ['employer_id'], unique=False)
    op.create_table('contact_grants',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('invitation_id', sa.String(length=36), nullable=False),
    sa.Column('employer_id', sa.String(length=36), nullable=False),
    sa.Column('candidate_id', sa.String(length=36), nullable=False),
    sa.Column('granted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['candidate_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['employer_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['invitation_id'], ['invitations.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('invitation_id')
    )
    op.create_index(op.f('ix_contact_grants_candidate_id'), 'contact_grants', ['candidate_id'], unique=False)
    op.create_index(op.f('ix_contact_grants_employer_id'), 'contact_grants', ['employer_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_contact_grants_employer_id'), table_name='contact_grants')
    op.drop_index(op.f('ix_contact_grants_candidate_id'), table_name='contact_grants')
    op.drop_table('contact_grants')
    op.drop_index(op.f('ix_search_snapshots_employer_id'), table_name='search_snapshots')
    op.drop_table('search_snapshots')
    op.drop_index(op.f('ix_invitations_employer_id'), table_name='invitations')
    op.drop_index(op.f('ix_invitations_candidate_id'), table_name='invitations')
    op.drop_table('invitations')
    op.drop_index(op.f('ix_login_sessions_user_id'), table_name='login_sessions')
    op.drop_table('login_sessions')
    op.drop_index(op.f('ix_hiring_needs_employer_id'), table_name='hiring_needs')
    op.drop_table('hiring_needs')
    op.drop_table('employer_profiles')
    op.drop_index(op.f('ix_email_tokens_user_id'), table_name='email_tokens')
    op.drop_table('email_tokens')
    op.drop_index(op.f('ix_candidate_profiles_verified_specialization'), table_name='candidate_profiles')
    op.drop_index(op.f('ix_candidate_profiles_verified_grade'), table_name='candidate_profiles')
    op.drop_table('candidate_profiles')
    op.drop_index(op.f('ix_assessment_attempts_candidate_id'), table_name='assessment_attempts')
    op.drop_table('assessment_attempts')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    op.drop_table('mail_outbox')
