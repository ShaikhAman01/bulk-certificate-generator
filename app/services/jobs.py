import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
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
REJECTED_AT_SUBMIT = (ErrorCode.VALIDATION_ERROR, ErrorCode.DUPLICATE_IN_JOB)


class IdempotencyKeyReused(Exception):
    """The Idempotency-Key was already used for a different request body."""


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


def create_job(
    db: Session,
    payload: JobCreate,
    idempotency_key: str | None = None,
    request_hash: str | None = None,
) -> CertificateJob:
    certificates = build_certificates(payload.recipients)
    job = CertificateJob(
        course_name=payload.certificate.course_name,
        issued_on=payload.certificate.issued_on,
        issuer=payload.certificate.issuer,
        total_count=len(certificates),
        status=JobStatus.PENDING,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
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


def request_fingerprint(payload: JobCreate) -> str:
    body = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def find_job_by_key(db: Session, idempotency_key: str) -> CertificateJob | None:
    return db.scalar(
        select(CertificateJob).where(CertificateJob.idempotency_key == idempotency_key)
    )


def create_job_idempotent(
    db: Session, payload: JobCreate, idempotency_key: str
) -> tuple[CertificateJob, bool]:
    """Return (job, created). A repeated key returns the original job instead of a new one."""
    fingerprint = request_fingerprint(payload)
    existing = find_job_by_key(db, idempotency_key)
    if existing is None:
        try:
            return create_job(db, payload, idempotency_key, fingerprint), True
        except IntegrityError:
            # a concurrent request with the same key committed first
            db.rollback()
            existing = find_job_by_key(db, idempotency_key)
            if existing is None:
                raise

    if existing.request_hash != fingerprint:
        raise IdempotencyKeyReused
    return existing, False


def count_rejected(db: Session, job_id) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Certificate)
        .where(Certificate.job_id == job_id, Certificate.error_code.in_(REJECTED_AT_SUBMIT))
    )


def retry_failed_certificates(db: Session, job: CertificateJob) -> int:
    requeued = db.execute(
        update(Certificate)
        .where(
            Certificate.job_id == job.id,
            Certificate.status == CertificateStatus.FAILED,
            Certificate.error_code == ErrorCode.GENERATION_ERROR,
        )
        .values(
            status=CertificateStatus.PENDING,
            error_code=None,
            error_message=None,
            attempts=0,
            locked_at=None,
            updated_at=func.now(),
        )
    ).rowcount
    if requeued:
        job.status = JobStatus.PROCESSING
        job.completed_at = None
    db.commit()
    return requeued
