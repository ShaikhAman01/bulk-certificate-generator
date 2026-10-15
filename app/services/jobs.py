from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Certificate,
    CertificateJob,
    CertificateStatus,
    ErrorCode,
    JobStatus,
)
from app.schemas import JobCreate, RecipientIn

RAW_VALUE_MAX = 500


def _raw_field(row: Any, key: str) -> str | None:
    if not isinstance(row, dict) or row.get(key) is None:
        return None
    return str(row[key])[:RAW_VALUE_MAX]


def _format_errors(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"]) or "row"
        msg = "must be an object with name and email" if err["type"] == "model_type" else err["msg"]
        parts.append(f"{field}: {msg}")
    return "; ".join(parts)


def build_certificates(rows: list[Any]) -> list[Certificate]:
    certificates = []
    first_row_for_email: dict[str, int] = {}

    for i, row in enumerate(rows):
        try:
            recipient = RecipientIn.model_validate(row)
        except ValidationError as exc:
            certificates.append(
                Certificate(
                    row_index=i,
                    recipient_name=_raw_field(row, "name"),
                    recipient_email=_raw_field(row, "email"),
                    status=CertificateStatus.FAILED,
                    error_code=ErrorCode.VALIDATION_ERROR,
                    error_message=_format_errors(exc),
                )
            )
            continue

        if recipient.email in first_row_for_email:
            first = first_row_for_email[recipient.email]
            certificates.append(
                Certificate(
                    row_index=i,
                    recipient_name=recipient.name,
                    recipient_email=recipient.email,
                    status=CertificateStatus.FAILED,
                    error_code=ErrorCode.DUPLICATE_IN_JOB,
                    error_message=f"email already used in row {first}",
                )
            )
            continue

        first_row_for_email[recipient.email] = i
        certificates.append(
            Certificate(
                row_index=i,
                recipient_name=recipient.name,
                recipient_email=recipient.email,
                status=CertificateStatus.PENDING,
            )
        )
    return certificates


def create_job(db: Session, payload: JobCreate) -> CertificateJob:
    certificates = build_certificates(payload.recipients)
    job = CertificateJob(
        course_name=payload.certificate.course_name,
        issued_on=payload.certificate.issued_on,
        issuer=payload.certificate.issuer,
        total_count=len(certificates),
        status=JobStatus.PENDING,
        certificates=certificates,
    )

    if all(c.status == CertificateStatus.FAILED for c in certificates):
        job.status = JobStatus.FAILED
        job.completed_at = datetime.now(UTC)

    db.add(job)
    db.commit()
    return job


def get_status_counts(db: Session, job_id) -> dict[CertificateStatus, int]:
    rows = db.execute(
        select(Certificate.status, func.count())
        .where(Certificate.job_id == job_id)
        .group_by(Certificate.status)
    ).all()
    return {status: count for status, count in rows}
