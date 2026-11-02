"""Runs inside the sandbox. Reads model-written code on stdin, runs it, prints ONE JSON result line.

Why a harness instead of `python -c code`:
- the user code runs in a child process, so a crash/exit in it can't stop us reporting
- charts are written to /tmp/out (tmpfs, size-capped) and returned base64 in the JSON,
  so the host never mounts a writable directory into the container
- output is truncated here, before it ever reaches the host or the model

Everything this prints is untrusted (the user code shares this uid and could tamper with it);
the host treats it as data only.
"""
import base64
import json
import os
import subprocess
import sys

TIMEOUT = int(os.environ.get("HARNESS_TIMEOUT", "15"))
MAX_TEXT = 20_000          # chars of stdout / stderr kept
MAX_FILES = 5
MAX_FILE_BYTES = 2_000_000
OUT_DIR = "/tmp/out"
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".svg", ".csv", ".txt", ".json"}


def clip(s: str) -> str:
    return s if len(s) <= MAX_TEXT else s[:MAX_TEXT] + f"\n...[truncated {len(s) - MAX_TEXT} chars]"


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    with open("/tmp/code.py", "w") as f:
        f.write(sys.stdin.read())

    result = {"exit_code": None, "timed_out": False, "stdout": "", "stderr": "", "files": []}
    try:
        p = subprocess.run(
            [sys.executable, "/tmp/code.py"],
            cwd=OUT_DIR, capture_output=True, text=True, errors="replace", timeout=TIMEOUT,
        )
        stderr = p.stderr
        if p.returncode == -9:
            # SIGKILL from the kernel OOM killer leaves no traceback; tell the model what happened.
            stderr += "\nKilled by SIGKILL: the code most likely exceeded the sandbox memory limit. Use less memory."
        elif p.returncode < 0:
            stderr += f"\nKilled by signal {-p.returncode}."
        result.update(exit_code=p.returncode, stdout=clip(p.stdout), stderr=clip(stderr))
    except subprocess.TimeoutExpired as e:
        out = e.stdout or ""
        out = out.decode(errors="replace") if isinstance(out, bytes) else out
        result.update(timed_out=True, stdout=clip(out),
                      stderr=f"Timed out after {TIMEOUT}s. Make the code faster or work on less data.")

    for name in sorted(os.listdir(OUT_DIR))[:MAX_FILES]:
        path = os.path.join(OUT_DIR, name)
        if not os.path.isfile(path) or os.path.splitext(name)[1].lower() not in ALLOWED_EXT:
            continue
        if os.path.getsize(path) > MAX_FILE_BYTES:
            continue
        with open(path, "rb") as f:
            result["files"].append({"name": name, "b64": base64.b64encode(f.read()).decode()})

    print(json.dumps(result))


main()
