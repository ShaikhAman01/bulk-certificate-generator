from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.db import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="Bulk Certificate Generator",
    description="A FastAPI application for generating bulk certificates.",
    lifespan=lifespan
)

@app.get("/health")
def health():
    return {"status": "ok"}


