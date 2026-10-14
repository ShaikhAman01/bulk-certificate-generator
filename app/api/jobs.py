import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Certificate, CertificateJob, CertificateStatus
from app.schemas import (
    CertificatePage,
    JobCreate,
    JobProgress,
    JobRead,
    JobSubmitResponse,
)
from app.services.jobs import create_job, get_status_counts

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
) -> JobSubmitResponse:
    job = create_job(db, payload)
    accepted = sum(c.status == CertificateStatus.PENDING for c in job.certificates)

    response.headers["Location"] = request.app.url_path_for("get_job", job_id=str(job.id))
    return JobSubmitResponse(
        id=job.id,
        status=job.status,
        total_count=job.total_count,
        accepted_count=accepted,
        rejected_count=job.total_count - accepted,
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
