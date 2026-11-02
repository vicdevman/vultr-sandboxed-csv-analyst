"""Containment check: run attacker code in the sandbox as if the model had obeyed a prompt injection.

The prompt guard is layer 1 and models can be talked out of it, so this skips the model entirely and asks:
if the model DID comply, what could its code reach? The verdict is decided on the host, by searching the
sandbox's output for the real secret values this process holds.
"""
import os
from pathlib import Path

from app import config
from app.sandbox import RunResult, run_python

ATTACKER_PAYLOAD = Path(__file__).resolve().parents[1] / "samples" / "attacker_payload.py"


def host_secrets() -> dict[str, str]:
    names = ("KEY", "TOKEN", "SECRET", "PASSWORD")
    found = {k: v for k, v in os.environ.items() if any(n in k.upper() for n in names) and len(v) >= 8}
    if config.INFERENCE_API_KEY:
        found["INFERENCE_API_KEY"] = config.INFERENCE_API_KEY
    return found


def run_attack(csv_path: str | None) -> tuple[str, RunResult, dict]:
    code = ATTACKER_PAYLOAD.read_text(encoding="utf-8")
    r = run_python(code, csv_path)
    secrets = host_secrets()
    everything = r.stdout + r.stderr + "".join(f["b64"] for f in r.files)
    lines = r.stdout.splitlines()
    blocked = sum(line.startswith("BLOCKED") for line in lines)
    reached = sum(line.startswith("REACHED") for line in lines)
    verdict = {
        "secrets_on_host": sorted(secrets),
        "leaked": sorted(k for k, v in secrets.items() if v in everything),
        "blocked": blocked,
        "attempts": blocked + reached,
    }
    return code, r, verdict
