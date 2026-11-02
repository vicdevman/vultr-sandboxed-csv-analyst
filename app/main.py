"""Web app: upload a CSV, then stream the agent's steps to the browser with Server-Sent Events.

Run: uvicorn app.main:app --port 8000
Two endpoints instead of one because the browser's EventSource only does GET:
  POST /api/upload                  -> {"id": ...}
  GET  /api/analyze?id=&q=&guard=   -> text/event-stream of agent events
  GET  /api/attack?id=              -> containment demo (attacker payload, no model)
"""
import json
import re
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app.agent import analyze
from app.containment import run_attack

UPLOAD_DIR = Path("uploads")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
UPLOAD_TTL_SECONDS = 3600
MAX_CONCURRENT_ANALYSES = 2  # each one may start a container; cap the load on the VM
MAX_QUESTION_CHARS = 1000

app = FastAPI(title="Sandboxed CSV Analyst")
slots = threading.BoundedSemaphore(MAX_CONCURRENT_ANALYSES)
UPLOAD_DIR.mkdir(exist_ok=True)


def cleanup_old_uploads() -> None:
    cutoff = time.time() - UPLOAD_TTL_SECONDS
    for p in UPLOAD_DIR.glob("*.csv"):
        if p.stat().st_mtime < cutoff:
            p.unlink(missing_ok=True)


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.post("/api/upload")
async def upload(file: UploadFile):
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"CSV larger than {MAX_UPLOAD_BYTES // 1024 // 1024} MB")
    if not data.strip():
        raise HTTPException(400, "Empty file")
    cleanup_old_uploads()
    # The server picks the filename, so the user's filename can never cause path traversal.
    file_id = uuid.uuid4().hex
    (UPLOAD_DIR / f"{file_id}.csv").write_bytes(data)
    return {"id": file_id, "name": file.filename, "bytes": len(data)}


def sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def upload_path(id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", id):
        raise HTTPException(400, "Bad id")
    path = UPLOAD_DIR / f"{id}.csv"
    if not path.exists():
        raise HTTPException(404, "Upload expired, please upload again")
    return path


@app.get("/api/analyze")
def analyze_stream(id: str, q: str, guard: bool = True):
    path = upload_path(id)
    if not q.strip() or len(q) > MAX_QUESTION_CHARS:
        raise HTTPException(400, f"Question must be 1-{MAX_QUESTION_CHARS} characters")
    return stream(lambda: analyze(str(path), q, guard=guard))


@app.get("/api/attack")
def attack_stream(id: str):
    """Containment demo: skip the model and run the attacker's payload as if the model had obeyed the CSV."""
    path = upload_path(id)

    def gen():
        yield {"type": "info", "content": "Simulated compromised model: running the attacker's payload directly."}
        code, r, verdict = run_attack(str(path))
        yield {"type": "code", "content": code, "attempt": 1}
        yield {"type": "result", "ok": r.ok, "exit_code": r.exit_code, "timed_out": r.timed_out,
               "stdout": r.stdout, "stderr": r.stderr, "files": r.files}
        # Counts only: the names of the host's env vars are none of the browser's business.
        yield {"type": "verdict", "secrets_on_host": len(verdict["secrets_on_host"]), "leaked": len(verdict["leaked"]),
               "blocked": verdict["blocked"], "attempts": verdict["attempts"]}

    return stream(gen)


def stream(gen) -> StreamingResponse:
    def events():
        if not slots.acquire(blocking=False):
            yield sse({"type": "error", "content": "Server busy, try again in a moment."})
            yield sse({"type": "done"})
            return
        try:
            for ev in gen():
                yield sse(ev)
        except Exception as e:  # inference outage, docker down, ...: tell the user, don't hang the stream
            yield sse({"type": "error", "content": f"{type(e).__name__}: {e}"})
        finally:
            slots.release()
        yield sse({"type": "done"})

    # Starlette runs this sync generator in a thread pool, so blocking model/docker calls are fine.
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
