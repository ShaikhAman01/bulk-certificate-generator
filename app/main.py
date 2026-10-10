from fastapi import FastAPI

app = FastAPI(title="Bulk Certificate Generator",
    description="A FastAPI application for generating bulk certificates."
)

@app.get("/health")
def health():
    return {"status": "ok"}
