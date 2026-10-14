import os
import uuid
from pathlib import Path

from app.config import settings


def certificate_relpath(job_id: uuid.UUID, cert_id: uuid.UUID) -> str:
    return f"certificates/{job_id}/{cert_id}.pdf"

def absolute_path(relpath:str) -> Path:
    return Path(settings.storage_dir) / relpath

def save_pdf(relpath: str, data: bytes) -> None:
    final = absolute_path(relpath)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.with_suffix(".pdf.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, final)
    