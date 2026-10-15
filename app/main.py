from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api import certificates as certificates_api
from app.api import jobs as jobs_api
from app.db import get_db, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Bulk Certificate Generator",
    description="A FastAPI application for generating bulk certificates.",
    lifespan=lifespan,
)

app.include_router(jobs_api.router, prefix="/api/v1")
app.include_router(certificates_api.router, prefix="/api/v1")


@app.get("/health")
def health(db: Annotated[Session, Depends(get_db)]):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ok"}
