import uuid
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
)

from app.config import settings
from app.models import CertificateStatus, ErrorCode, JobStatus


class RecipientIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    email: Annotated[EmailStr, AfterValidator(str.lower)]


class CertificateInfo(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    course_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    issued_on: date
    issuer: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = None


class JobCreate(BaseModel):
    certificate: CertificateInfo
    recipients: list[Any] = Field(min_length=1, max_length=settings.max_recipients_per_job)


class JobSubmitResponse(BaseModel):
    id: uuid.UUID
    status: JobStatus
    total_count: int
    accepted_count: int
    rejected_count: int


class JobRetryResponse(BaseModel):
    id: uuid.UUID
    status: JobStatus
    requeued_count: int


class JobProgress(BaseModel):
    total: int
    pending: int
    processing: int
    succeeded: int
    failed: int


class JobRead(BaseModel):
    id: uuid.UUID
    status: JobStatus
    course_name: str
    issued_on: date
    issuer: str | None
    template_id: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    progress: JobProgress


class CertificateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    row_index: int
    recipient_name: str | None
    recipient_email: str | None
    status: CertificateStatus
    error_code: ErrorCode | None
    error_message: str | None
    certificate_number: str | None
    created_at: datetime
    updated_at: datetime


class CertificatePage(BaseModel):
    items: list[CertificateRead]
    total: int
    limit: int
    offset: int
