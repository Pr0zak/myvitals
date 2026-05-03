from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import ingest


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="myvitals", version="0.1.0", lifespan=lifespan)

app.include_router(ingest.router, prefix="/ingest", tags=["ingest"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
