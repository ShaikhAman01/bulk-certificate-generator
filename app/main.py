from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import certificates as certificates_api
from app.api import jobs as jobs_api
from app.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="Bulk Certificate Generator",
    description="A FastAPI application for generating bulk certificates.",
    lifespan=lifespan
)

app.include_router(jobs_api.router, prefix="/api/v1")
app.include_router(certificates_api.router, prefix="/api/v1")

@app.get("/health")
def health():
    return {"status": "ok"}


