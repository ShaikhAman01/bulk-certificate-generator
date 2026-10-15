import logging
import secrets
import uuid
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import (
    Certificate,
    CertificateJob,
    CertificateStatus,
    ErrorCode,
    JobStatus,
)
from app.services.jobs import get_status_counts
from app.services.renderer import render_certificate_pdf
from app.services.storage import certificate_relpath, save_pdf

logger = logging.getLogger(__name__)

NUMBER_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_certificate_number() -> str:
    return "CERT-" + "".join(secrets.choice(NUMBER_ALPHABET) for _ in range(8))


def claim_batch(session_factory: sessionmaker[Session], limit: int) -> list[uuid.UUID]:
    with session_factory() as db:
        pending_ids = (
            select(Certificate.id)
            .where(Certificate.status == CertificateStatus.PENDING)
            .order_by(Certificate.created_at, Certificate.row_index)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        claimed = db.execute(
            update(Certificate)
            .where(Certificate.id.in_(pending_ids))
            .values(
                status=CertificateStatus.PROCESSING,
                locked_at=func.now(),
                attempts=Certificate.attempts + 1,
                updated_at=func.now(),
            )
            .returning(Certificate.id, Certificate.job_id)
            .execution_options(synchronize_session=False)
        ).all()

        job_ids = {job_id for _, job_id in claimed}
        if job_ids:
            db.execute(
                update(CertificateJob)
                .where(
                    CertificateJob.id.in_(job_ids),
                    CertificateJob.status == JobStatus.PENDING,
                )
                .values(status=JobStatus.PROCESSING, started_at=func.now())
            )
        db.commit()
        return [cert_id for cert_id, _ in claimed]


def process_certificate(session_factory: sessionmaker[Session], cert_id: uuid.UUID) -> None:
    with session_factory() as db:
        cert = db.get(Certificate, cert_id)
        if cert is None or cert.status != CertificateStatus.PROCESSING:
            return
        job = cert.job
        job_id = job.id

        try:
            number = generate_certificate_number()
            pdf = render_certificate_pdf(
                {
                    "recipient_name": cert.recipient_name,
                    "course_name": job.course_name,
                    "issued_on": job.issued_on,
                    "issuer": job.issuer,
                    "certificate_number": number,
                },
                job.template_id,
            )
            relpath = certificate_relpath(job_id, cert_id)
            save_pdf(relpath, pdf)

            cert.status = CertificateStatus.SUCCEEDED
            cert.certificate_number = number
            cert.file_path = relpath
            cert.error_code = None
            cert.error_message = None
            cert.locked_at = None
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.exception("certificate %s failed", cert_id)
            cert = db.get(Certificate, cert_id)
            cert.status = CertificateStatus.FAILED
            cert.error_code = ErrorCode.GENERATION_ERROR
            cert.error_message = f"{type(exc).__name__}: {exc}"[:500]
            cert.locked_at = None
            db.commit()

        finalize_job_if_done(db, job_id)


def finalize_job_if_done(db: Session, job_id: uuid.UUID) -> None:
    counts = get_status_counts(db, job_id)
    if counts.get(CertificateStatus.PENDING) or counts.get(CertificateStatus.PROCESSING):
        return

    succeeded = counts.get(CertificateStatus.SUCCEEDED, 0)
    failed = counts.get(CertificateStatus.FAILED, 0)
    if failed == 0:
        status = JobStatus.COMPLETED
    elif succeeded == 0:
        status = JobStatus.FAILED
    else:
        status = JobStatus.PARTIALLY_FAILED

    db.execute(
        update(CertificateJob)
        .where(
            CertificateJob.id == job_id,
            CertificateJob.status.in_([JobStatus.PENDING, JobStatus.PROCESSING]),
        )
        .values(status=status, completed_at=func.now())
    )
    db.commit()


def recover_stale(session_factory: sessionmaker[Session]) -> None:
    cutoff = func.now() - timedelta(seconds=settings.lease_timeout_seconds)
    is_stale = (
        Certificate.status == CertificateStatus.PROCESSING,
        Certificate.locked_at < cutoff,
    )

    with session_factory() as db:
        requeued = db.execute(
            update(Certificate)
            .where(*is_stale, Certificate.attempts < settings.max_attempts)
            .values(status=CertificateStatus.PENDING, locked_at=None, updated_at=func.now())
            .execution_options(synchronize_session=False)
        ).rowcount
        given_up_job_ids = (
            db.execute(
                update(Certificate)
                .where(*is_stale, Certificate.attempts >= settings.max_attempts)
                .values(
                    status=CertificateStatus.FAILED,
                    error_code=ErrorCode.GENERATION_ERROR,
                    error_message=f"worker lease expired {settings.max_attempts} times",
                    locked_at=None,
                    updated_at=func.now(),
                )
                .returning(Certificate.job_id)
                .execution_options(synchronize_session=False)
            )
            .scalars()
            .all()
        )
        db.commit()

        if requeued or given_up_job_ids:
            logger.warning("stale sweep: requeued=%s gave_up=%s", requeued, len(given_up_job_ids))
        for job_id in set(given_up_job_ids):
            finalize_job_if_done(db, job_id)
