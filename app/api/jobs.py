import logging
import tempfile
import uuid
import zipfile
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.db import get_db
from app.models import Certificate, CertificateJob, CertificateStatus, JobStatus
from app.schemas import (
    CertificatePage,
    JobCreate,
    JobProgress,
    JobRead,
    JobRetryResponse,
    JobSubmitResponse,
)
from app.services.jobs import (
    IdempotencyKeyReused,
    count_rejected,
    create_job,
    create_job_idempotent,
    get_status_counts,
    retry_failed_certificates,
)
from app.services.storage import absolute_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/certificate-jobs", tags=["certificate-jobs"])


def get_job_or_404(db: Session, job_id: uuid.UUID) -> CertificateJob:
    job = db.get(CertificateJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.post("", status_code=202, response_model=JobSubmitResponse)
def submit_job(
    payload: JobCreate,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(min_length=1, max_length=100)] = None,
) -> JobSubmitResponse:
    if idempotency_key is None:
        job = create_job(db, payload)
    else:
        try:
            job, created = create_job_idempotent(db, payload, idempotency_key)
        except IdempotencyKeyReused:
            raise HTTPException(
                status_code=422,
                detail="Idempotency-Key was already used with a different request body",
            ) from None
        if not created:
            response.headers["Idempotent-Replayed"] = "true"

    rejected = count_rejected(db, job.id)
    response.headers["Location"] = request.app.url_path_for("get_job", job_id=str(job.id))
    return JobSubmitResponse(
        id=job.id,
        status=job.status,
        total_count=job.total_count,
        accepted_count=job.total_count - rejected,
        rejected_count=rejected,
    )


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]) -> JobRead:
    job = get_job_or_404(db, job_id)
    counts = get_status_counts(db, job_id)
    return JobRead(
        id=job.id,
        status=job.status,
        course_name=job.course_name,
        issued_on=job.issued_on,
        issuer=job.issuer,
        template_id=job.template_id,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        progress=JobProgress(
            total=job.total_count,
            pending=counts.get(CertificateStatus.PENDING, 0),
            processing=counts.get(CertificateStatus.PROCESSING, 0),
            succeeded=counts.get(CertificateStatus.SUCCEEDED, 0),
            failed=counts.get(CertificateStatus.FAILED, 0),
        ),
    )


@router.get("/{job_id}/certificates", response_model=CertificatePage)
def list_job_certificates(
    job_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    status: CertificateStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CertificatePage:
    get_job_or_404(db, job_id)

    filters = [Certificate.job_id == job_id]
    if status is not None:
        filters.append(Certificate.status == status)

    total = db.scalar(select(func.count()).select_from(Certificate).where(*filters))
    rows = db.scalars(
        select(Certificate)
        .where(*filters)
        .order_by(Certificate.row_index)
        .limit(limit)
        .offset(offset)
    ).all()
    return CertificatePage(items=rows, total=total, limit=limit, offset=offset)


@router.get("/{job_id}/download", response_class=StreamingResponse)
def download_job_zip(
    job_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]
) -> StreamingResponse:
    job = get_job_or_404(db, job_id)
    if job.status in (JobStatus.PENDING, JobStatus.PROCESSING):
        raise HTTPException(
            status_code=409, detail=f"job is {job.status.value}, wait until it finishes"
        )

    certs = db.scalars(
        select(Certificate)
        .where(Certificate.job_id == job_id, Certificate.status == CertificateStatus.SUCCEEDED)
        .order_by(Certificate.row_index)
    ).all()
    if not certs:
        raise HTTPException(status_code=409, detail="job has no generated certificates")

    # closed by the background task after the response is sent, so no with-block
    archive = tempfile.SpooledTemporaryFile(max_size=10 * 1024 * 1024)  # noqa: SIM115
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zf:
        for cert in certs:
            path = absolute_path(cert.file_path)
            if not path.is_file():
                logger.error("certificate %s is SUCCEEDED but %s is missing", cert.id, path)
                continue
            zf.write(path, arcname=f"{cert.row_index:04d}-{cert.certificate_number}.pdf")
    archive.seek(0)

    return StreamingResponse(
        iter(lambda: archive.read(64 * 1024), b""),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="certificates-{job_id}.zip"'},
        background=BackgroundTask(archive.close),
    )


@router.post("/{job_id}/retry", status_code=202, response_model=JobRetryResponse)
def retry_job(
    job_id: uuid.UUID,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> JobRetryResponse:
    job = get_job_or_404(db, job_id)
    if job.status in (JobStatus.PENDING, JobStatus.PROCESSING):
        raise HTTPException(
            status_code=409, detail=f"job is {job.status.value}, wait until it finishes"
        )

    requeued = retry_failed_certificates(db, job)
    if not requeued:
        raise HTTPException(status_code=409, detail="job has no retryable certificates")

    response.headers["Location"] = request.app.url_path_for("get_job", job_id=str(job.id))
    return JobRetryResponse(id=job.id, status=job.status, requeued_count=requeued)
