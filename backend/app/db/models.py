from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Enum as SQLEnum,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.session import Base


class ExamType(str, Enum):
    FE = "FE"
    PE = "PE"


class ExamStatus(str, Enum):
    PENDING = "pending"
    CRAWLED = "crawled"
    FAILED = "failed"


class QuestionType(str, Enum):
    SINGLE = "single"
    MULTIPLE = "multiple"
    UNKNOWN = "unknown"


class AnswerStatus(str, Enum):
    CONFIDENT = "confident"  # >= 0.7 confidence and >= 3 comments
    WEAK = "weak"            # 0.5 - 0.7 or few comments
    CONFLICT = "conflict"    # top-2 answers are close
    NO_DATA = "no_data"      # no comments available


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    forum_url: Mapped[str] = mapped_column(String(500), nullable=False)
    exam_count: Mapped[int] = mapped_column(Integer, default=0)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    exams: Mapped[List["Exam"]] = relationship("Exam", back_populates="subject", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Subject {self.code}: {self.name}>"


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    subject_id: Mapped[int] = mapped_column(Integer, ForeignKey("subjects.id"), nullable=False, index=True)
    exam_type: Mapped[ExamType] = mapped_column(SQLEnum(ExamType), nullable=False, default=ExamType.FE, index=True)
    term: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # e.g. SU26, FA24
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(500), unique=True, nullable=False, index=True)
    post_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    question_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[ExamStatus] = mapped_column(SQLEnum(ExamStatus), default=ExamStatus.PENDING, index=True)
    raw_folder: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    subject: Mapped["Subject"] = relationship("Subject", back_populates="exams")
    questions: Mapped[List["Question"]] = relationship("Question", back_populates="exam", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Exam {self.exam_type} id={self.id}: {self.title}>"


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    exam_id: Mapped[int] = mapped_column(Integer, ForeignKey("exams.id"), nullable=False, index=True)
    index: Mapped[int] = mapped_column(Integer, nullable=False)  # Question 1, 2, ...
    file_name: Mapped[str] = mapped_column(String(100), nullable=False)  # Q1.webp
    cdn_image_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    local_image_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    phash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    qtype: Mapped[QuestionType] = mapped_column(SQLEnum(QuestionType), default=QuestionType.UNKNOWN)
    media_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    media_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    exam: Mapped["Exam"] = relationship("Exam", back_populates="questions")
    comments: Mapped[List["Comment"]] = relationship("Comment", back_populates="question", cascade="all, delete-orphan")
    answer: Mapped[Optional["Answer"]] = relationship("Answer", back_populates="question", uselist=False, cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Question exam_id={self.exam_id} index={self.index}: {self.file_name}>"


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    question_id: Mapped[int] = mapped_column(Integer, ForeignKey("questions.id"), nullable=False, index=True)
    comment_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    author_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # Anonymized author hash
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    upvotes: Mapped[int] = mapped_column(Integer, default=0)
    is_reply: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_comment_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    quoted_comment_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    html_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    question: Mapped["Question"] = relationship("Question", back_populates="comments")

    def __repr__(self) -> str:
        return f"<Comment id={self.id} question_id={self.question_id} upvotes={self.upvotes}>"


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    question_id: Mapped[int] = mapped_column(Integer, ForeignKey("questions.id"), unique=True, nullable=False, index=True)
    answer_set: Mapped[List[str]] = mapped_column(JSON, default=list)  # e.g. ["A"] or ["A", "C"]
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[AnswerStatus] = mapped_column(SQLEnum(AnswerStatus), default=AnswerStatus.NO_DATA, index=True)
    valid_comments_count: Mapped[int] = mapped_column(Integer, default=0)
    vote_breakdown: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    question: Mapped["Question"] = relationship("Question", back_populates="answer")

    def __repr__(self) -> str:
        return f"<Answer question_id={self.question_id} answers={self.answer_set} conf={self.confidence:.2f}>"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    fuo_user_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    last_login_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    jobs: Mapped[List["Job"]] = relationship("Job", back_populates="user")

    def __repr__(self) -> str:
        return f"<User {self.username}>"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    subject_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    exam_type: Mapped[ExamType] = mapped_column(SQLEnum(ExamType), default=ExamType.FE)
    exam_count: Mapped[int] = mapped_column(Integer, default=4)
    status: Mapped[JobStatus] = mapped_column(SQLEnum(JobStatus), default=JobStatus.PENDING, index=True)
    progress_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    current_step: Mapped[str] = mapped_column(String(255), default="Initialized")
    result_file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    details: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    config_snapshot: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="jobs")

    def __repr__(self) -> str:
        return f"<Job {self.job_id} [{self.status}] {self.subject_code} {self.exam_type}>"


class Setting(Base):
    """Stores user-configured application settings overriding config.yaml defaults."""
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True, index=True)
    value: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Setting key={self.key} updated_at={self.updated_at}>"


