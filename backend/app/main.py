"""FastAPI entrypoint for ContextCue hackathon starter."""

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .planner import plan
from .schemas import PlanRequest, PlanResponse

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
app = FastAPI(title="ContextCue API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/plan", response_model=PlanResponse)
async def make_plan(request: PlanRequest):
    try:
        return await plan(request)
    except Exception as exc:
        # No transparent fallback to fake results when the live provider fails.
        raise HTTPException(
            status_code=502, detail=f"AI planner unavailable: {type(exc).__name__}"
        ) from exc
