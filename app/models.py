import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

class JobStatus(enum.StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    PARTIALLY_FAILED = "PARTIALLY_FAILED"
    FAILED = "FAILED"

class CertificateStatus(enum.StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"

class ErrorCode(enum.StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    DUPLICATE_IN_JOB = "DUPLICATE_IN_JOB"
    GENERATION_ERROR = "GENERATION_ERROR"

class CertificateJob(Base):
    __tablename__ = "certificate_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, create_constraint=True, length=20),
        default=JobStatus.PENDING,
    )
    course_name: Mapped[str] = mapped_column(String(200))
    issued_on: Mapped[date] = mapped_column(Date)
    issuer: Mapped[str | None] = mapped_column(String(200))
    template_id: Mapped[str] = mapped_column(String(50), default="default_v1")
    total_count: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    certificates: Mapped[list["Certificate"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", passive_deletes=True
    )

class Certificate(Base):
    __tablename__ = "certificates"
    __table_args__ = (
        UniqueConstraint("job_id", "row_index"),
        Index("ix_certificates_job_id_status", "job_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("certificate_jobs.id", ondelete="CASCADE")
    )
    row_index: Mapped[int]
    recipient_name: Mapped[str | None] = mapped_column(Text)
    recipient_email: Mapped[str | None] = mapped_column(Text)
    status: Mapped[CertificateStatus] = mapped_column(
        Enum(CertificateStatus, native_enum=False, create_constraint=True, length=20),
        default=CertificateStatus.PENDING,
    )
    error_code: Mapped[ErrorCode | None] = mapped_column(
        Enum(ErrorCode, native_enum=False, create_constraint=True, length=30)
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(String(500))
    certificate_number: Mapped[str | None] = mapped_column(String(20), unique=True)
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    job: Mapped[CertificateJob] = relationship(back_populates="certificates")
