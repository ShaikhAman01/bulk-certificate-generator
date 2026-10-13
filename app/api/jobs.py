from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import CertificateStatus
from app.schemas import JobCreate, JobSubmitResponse
from app.services.jobs import create_job

router = APIRouter(prefix="/certificate-jobs", tags=["certificate-jobs"])

@router.post("", status_code=202, response_model=JobSubmitResponse)
def submit_job(
    payload: JobCreate,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> JobSubmitResponse:
    job = create_job(db, payload)
    accepted = sum(c.status == CertificateStatus.PENDING for c in job.certificates)

    response.headers["Location"] = f"/api/v1/certificate-jobs/{job.id}"
    return JobSubmitResponse(
        id=job.id,
        status=job.status,
        total_count=job.total_count,
        accepted_count=accepted,
        rejected_count=job.total_count - accepted,
    )
