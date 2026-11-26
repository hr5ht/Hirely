"""Tables keep the names and columns the Django app used, so its data and password hashes still work."""
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import (JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, LargeBinary, Numeric, SmallInteger, String,
                        Text, UniqueConstraint)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from app.core.database import Base

Json = JSON().with_variant(JSONB(), 'postgresql')


def now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = 'auth_user'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    password: Mapped[str] = mapped_column(String(128), default='!')  # '!...' = unusable
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    username: Mapped[str] = mapped_column(String(150), unique=True)
    first_name: Mapped[str] = mapped_column(String(150), default='')
    last_name: Mapped[str] = mapped_column(String(150), default='')
    email: Mapped[str] = mapped_column(String(254), default='')
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    date_joined: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    # Deleting a user (e.g. in /admin/) deletes the profile; without the cascade the ORM would blank its user_id and fail
    profile: Mapped['UserProfile | None'] = relationship(back_populates='user', lazy='selectin', cascade='all, delete-orphan',
                                                         passive_deletes=True)

    def __str__(self):
        return self.username


class Company(Base):
    __tablename__ = 'ai_engine_company'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    domain: Mapped[str] = mapped_column(String(255), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    def __str__(self):
        return self.name


class CompanyInvite(Base):
    """A one-time link that lets a new recruiter register into an existing company."""
    __tablename__ = 'ai_engine_companyinvite'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: secrets.token_urlsafe(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: now() + timedelta(days=7))
    company_id: Mapped[int] = mapped_column(ForeignKey('ai_engine_company.id', ondelete='CASCADE'), index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey('auth_user.id', ondelete='SET NULL'), index=True)
    used_by_id: Mapped[int | None] = mapped_column(ForeignKey('auth_user.id', ondelete='SET NULL'), index=True)

    company: Mapped[Company] = relationship(lazy='selectin')
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id], lazy='selectin')

    @property
    def is_usable(self):
        return self.used_by_id is None and self.expires_at > now()


class UserProfile(Base):
    __tablename__ = 'ai_engine_userprofile'
    ROLE_CHOICES = (('candidate', 'Candidate'), ('recruiter', 'Recruiter'), ('admin', 'Admin'))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(String(50), default='candidate')
    user_id: Mapped[int] = mapped_column(ForeignKey('auth_user.id', ondelete='CASCADE'), unique=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey('ai_engine_company.id', ondelete='SET NULL'), index=True)
    resume_pdf: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)  # default resume saved on the profile
    resume_text: Mapped[str] = mapped_column(Text, default='')

    user: Mapped[User] = relationship(back_populates='profile', lazy='selectin')
    company: Mapped[Company | None] = relationship(lazy='selectin')

    def __str__(self):
        return f"{self.user.username} ({dict(self.ROLE_CHOICES).get(self.role, self.role)})"


class Job(Base):
    __tablename__ = 'ai_engine_job'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey('ai_engine_company.id', ondelete='CASCADE'), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    experience_level: Mapped[str] = mapped_column(String(50), default='')
    interview_rounds: Mapped[int] = mapped_column(SmallInteger, default=5)
    answer_time_limit: Mapped[int] = mapped_column(SmallInteger, default=0)  # seconds per question, 0 = no limit
    custom_questions: Mapped[list] = mapped_column(Json, default=list)  # recruiter's must-ask questions, in order
    # How much each interview score counts toward the overall score (relative weights, need not sum to 100)
    weight_tech: Mapped[int] = mapped_column(SmallInteger, default=40)
    weight_behavioral: Mapped[int] = mapped_column(SmallInteger, default=30)
    weight_problem_solving: Mapped[int] = mapped_column(SmallInteger, default=30)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    company: Mapped[Company] = relationship(lazy='selectin')

    def __str__(self):
        return f"{self.title} at {self.company.name}"


WEIGHT_DEFAULTS = {'weight_tech': 40, 'weight_behavioral': 30, 'weight_problem_solving': 30}


class Application(Base):
    __tablename__ = 'ai_engine_application'
    __table_args__ = (UniqueConstraint('job_id', 'candidate_id', name='unique_job_candidate'),)
    STATUS_CHOICES = (('applied', 'Applied'), ('interviewing', 'Interviewing'), ('evaluated', 'Evaluated'),
                      ('accepted', 'Accepted'), ('rejected', 'Rejected'))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey('ai_engine_job.id', ondelete='CASCADE'), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey('auth_user.id', ondelete='CASCADE'), index=True)
    resume_pdf: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    resume_text: Mapped[str] = mapped_column(Text, default='')
    ats_match_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    # skill/semantic sub-scores, matching/missing keywords and suggestions from the ATS scan
    ats_breakdown: Mapped[dict] = mapped_column(Json, default=dict)
    proctoring_score: Mapped[int] = mapped_column(Integer, default=100)
    recruiter_notes: Mapped[str] = mapped_column(Text, default='')  # private to the hiring company
    status: Mapped[str] = mapped_column(String(50), default='applied')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    has_resume_pdf: Mapped[bool] = column_property(resume_pdf.is_not(None))  # without loading the bytes

    job: Mapped[Job] = relationship(lazy='selectin')
    candidate: Mapped[User] = relationship(lazy='selectin')
    sessions: Mapped[list['InterviewSession']] = relationship(back_populates='application', lazy='selectin', order_by='InterviewSession.id',
                                                              cascade='all, delete-orphan', passive_deletes=True)

    @property
    def status_display(self):
        return dict(self.STATUS_CHOICES).get(self.status, self.status)

    @property
    def interview_score(self):
        """Overall interview score using the job's weights, or None before the interview is completed."""
        session = next((s for s in self.sessions if s.session_status == 'completed'), None)
        if not session:
            return None
        weights = (self.job.weight_tech, self.job.weight_behavioral, self.job.weight_problem_solving)
        scores = (session.tech_knowledge, session.behavioral_iq, session.problem_solving)
        return round(sum(w * s for w, s in zip(weights, scores)) / (sum(weights) or 1))

    def __str__(self):
        return f"{self.candidate.username} for {self.job.title}"


class InterviewSession(Base):
    __tablename__ = 'ai_engine_interviewsession'
    STATUS_CHOICES = (('pending', 'Pending'), ('active', 'Active'), ('completed', 'Completed'), ('disconnected', 'Disconnected'))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey('ai_engine_application.id', ondelete='CASCADE'), index=True)
    session_status: Mapped[str] = mapped_column(String(50), default='pending')
    transcript: Mapped[list] = mapped_column(Json, default=list)
    proctoring_logs: Mapped[list] = mapped_column(Json, default=list)
    pdf_report: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    avg_confidence: Mapped[int] = mapped_column(Integer, default=0)
    avg_clarity: Mapped[int] = mapped_column(Integer, default=0)
    tech_knowledge: Mapped[int] = mapped_column(Integer, default=0)
    behavioral_iq: Mapped[int] = mapped_column(Integer, default=0)
    problem_solving: Mapped[int] = mapped_column(Integer, default=0)
    gap_analysis: Mapped[str] = mapped_column(Text, default='')
    rag_cache: Mapped[dict] = mapped_column(Json, default=dict, deferred=True)  # embedded resume/JD chunks, see rag.retrieve
    heartbeats: Mapped[list] = mapped_column(Json, default=list)  # server epoch seconds of each live-camera ping
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    has_pdf: Mapped[bool] = column_property(pdf_report.is_not(None))

    application: Mapped[Application] = relationship(back_populates='sessions', lazy='selectin')

    @property
    def status_display(self):
        return dict(self.STATUS_CHOICES).get(self.session_status, self.session_status)

    @property
    def trend_bars(self):
        """(label, score, bar colour) rows for the candidate's score trend."""
        return [("Technical", self.tech_knowledge, "fill-blue"), ("Behavioral", self.behavioral_iq, "fill-violet"),
                ("Problem solving", self.problem_solving, "fill-pink")]


class RateLimit(Base):
    """Fixed-window attempt counters shared by every worker (replaces Django's DB cache table)."""
    __tablename__ = 'rate_limit'
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    count: Mapped[int] = mapped_column(BigInteger, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
