from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import version as version_mod
from .api import ingest


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="myvitals", version=version_mod.__version__, lifespan=lifespan)

app.include_router(ingest.router, prefix="/ingest", tags=["ingest"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/version")
async def get_version() -> dict[str, str]:
    return version_mod.info()
