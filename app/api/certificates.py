import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Certificate, CertificateStatus
from app.schemas import CertificateRead
from app.services.storage import absolute_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/certificates", tags=["certificates"])


def get_certificate_or_404(db: Session, cert_id: uuid.UUID) -> Certificate:
    cert = db.get(Certificate, cert_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="certificate not found")
    return cert


@router.get("/{cert_id}", response_model=CertificateRead)
def get_certificate(cert_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]) -> Certificate:
    return get_certificate_or_404(db, cert_id)


@router.get("/{cert_id}/pdf", response_class=FileResponse)
def download_certificate_pdf(
    cert_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]
) -> FileResponse:
    cert = get_certificate_or_404(db, cert_id)
    if cert.status != CertificateStatus.SUCCEEDED or cert.file_path is None:
        raise HTTPException(
            status_code=409,
            detail=f"certificate is {cert.status.value}, PDF not available",
        )

    path = absolute_path(cert.file_path)
    if not path.is_file():
        logger.error("certificate %s is SUCCEEDED but %s is missing", cert_id, path)
        raise HTTPException(status_code=500, detail="certificate file is missing")

    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"certificate-{cert.certificate_number}.pdf",
    )
