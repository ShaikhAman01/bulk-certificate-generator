import uuid
from datetime import date
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
from app.models import JobStatus


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
    recipients: list[Any] = Field(
        min_length=1, max_length=settings.max_recipients_per_job
    )

class JobSubmitResponse(BaseModel):
    id: uuid.UUID
    status: JobStatus
    total_count: int
    accepted_count: int
    rejected_count: int

