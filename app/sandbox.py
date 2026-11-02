"""Host-side sandbox runner: one fresh, locked-down container per code run, destroyed afterwards.

The container gets exactly two things: the code (on stdin) and the CSV (read-only bind mount).
No env vars, no network, no writable mounts, no capabilities. Results come back as one JSON line.
"""
import json
import os
import subprocess
import uuid
from dataclasses import dataclass, field

from app import config

CSV_PATH_IN_SANDBOX = "/data/input.csv"
MAX_HOST_READ = 15_000_000  # bytes of container stdout we will parse, at most


@dataclass
class RunResult:
    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str
    files: list[dict] = field(default_factory=list)  # [{"name": str, "b64": str}]

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def docker_command(name: str, csv_path: str | None) -> list[str]:
    # Container-side limit is the harness timeout; the host kills a few seconds later as a backstop.
    cmd = [
        "docker", "run", "--rm", "-i",
        "--name", name,
        "--runtime", config.SANDBOX_RUNTIME,
        "--network", "none",                       # no egress, no exfiltration
        "--read-only",                             # immutable root fs
        "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m",  # only writable place, size-capped, gone on exit
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--user", "10001:10001",
        "--memory", config.SANDBOX_MEMORY,
        "--memory-swap", config.SANDBOX_MEMORY,    # = memory, so no swap headroom
        "--cpus", config.SANDBOX_CPUS,
        "--pids-limit", config.SANDBOX_PIDS_LIMIT,  # stops fork bombs
        "--ipc", "none",
        "--log-driver", "none",                    # don't keep a copy of output in docker logs
        "-e", f"HARNESS_TIMEOUT={config.SANDBOX_TIMEOUT_SECONDS}",  # the only env var, and not a secret
    ]
    if csv_path:
        src = os.path.abspath(csv_path)
        cmd += ["--mount", f"type=bind,src={src},dst={CSV_PATH_IN_SANDBOX},readonly"]
    return cmd + [config.SANDBOX_IMAGE]


def run_python(code: str, csv_path: str | None = None) -> RunResult:
    name = f"csv-sbx-{uuid.uuid4().hex[:12]}"
    try:
        p = subprocess.run(
            docker_command(name, csv_path),
            input=code.encode(), capture_output=True,
            timeout=config.SANDBOX_TIMEOUT_SECONDS + 10,
        )
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", name], capture_output=True)
        return RunResult(None, True, "", "Sandbox killed by host after hard timeout")
    finally:
        # --rm should have removed it; make sure, even after a kill or a docker hiccup.
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)

    raw = p.stdout[:MAX_HOST_READ].decode(errors="replace").strip()
    try:
        data = json.loads(raw.splitlines()[-1])
        return RunResult(data["exit_code"], data["timed_out"], data["stdout"], data["stderr"], data["files"])
    except (IndexError, ValueError, KeyError, TypeError):
        # Harness never reported: container was OOM-killed (137), failed to start, etc.
        err = p.stderr.decode(errors="replace")[-2000:]
        if p.returncode == 137:
            err = "Sandbox was killed (out of memory - limit is %s). %s" % (config.SANDBOX_MEMORY, err)
        return RunResult(p.returncode, False, raw[-2000:], err)
