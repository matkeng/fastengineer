"""FastAPI adapter. Keep this thin: all real work belongs in workbench_core."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import workbench_core
from workbench_core.hello import EngineInfo, Greeting
from workbench_core.model import Equipment

from .excel_api import router as excel_router
from .mel_api import router as mel_router
from .symbols_api import router as symbols_router
from .refdata_api import router as refdata_router

app = FastAPI(title="Drawing Workbench engine", version=workbench_core.__version__)

# The Tauri WebView origin differs by OS (http://tauri.localhost on Windows,
# tauri://localhost on macOS/Linux); Vite dev server runs on localhost:5173.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(https?://tauri\.localhost|tauri://localhost|http://localhost:\d+|http://127\.0\.0\.1:\d+)$",
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


app.include_router(excel_router)
app.include_router(mel_router)
app.include_router(refdata_router)
app.include_router(symbols_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/info", response_model=EngineInfo)
def info() -> EngineInfo:
    return workbench_core.engine_info()


@app.get("/api/hello", response_model=Greeting)
def hello(name: str = "world") -> Greeting:
    return workbench_core.greet(name)


@app.get("/api/model/demo", response_model=list[Equipment])
def model_demo() -> list[Equipment]:
    return workbench_core.demo_equipment()
