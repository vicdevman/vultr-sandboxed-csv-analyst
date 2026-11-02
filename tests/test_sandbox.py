"""Containment tests: each one is an attack (or a mistake) the sandbox must survive.

Needs Docker and the image: docker build -t csv-analyst-sandbox:latest sandbox
Run: pytest -v tests/test_sandbox.py
"""
import base64
import os
import subprocess
import textwrap

import pytest

from app import config
from app.sandbox import run_python


@pytest.fixture
def csv_file(tmp_path):
    p = tmp_path / "sales.csv"
    p.write_text("region,amount\nnorth,10\nsouth,32\nnorth,5\n")
    return str(p)


def run(code, csv=None):
    return run_python(textwrap.dedent(code), csv)


def test_happy_path_reads_csv(csv_file):
    r = run("""
        import pandas as pd
        df = pd.read_csv("/data/input.csv")
        print(df.groupby("region")["amount"].sum().to_dict())
    """, csv_file)
    assert r.ok, r.stderr
    assert "{'north': 15, 'south': 32}" in r.stdout


def test_chart_comes_back_as_file(csv_file):
    r = run("""
        import pandas as pd, matplotlib.pyplot as plt
        pd.read_csv("/data/input.csv").plot.bar(x="region", y="amount")
        plt.savefig("chart.png")
    """, csv_file)
    assert r.ok, r.stderr
    assert r.files[0]["name"] == "chart.png"
    assert base64.b64decode(r.files[0]["b64"]).startswith(b"\x89PNG")


def test_traceback_is_returned_for_repair():
    r = run("import pandas as pd\npd.read_csv('/data/nope.csv')")
    assert not r.ok
    assert "FileNotFoundError" in r.stderr


def test_no_network():
    r = run("""
        import socket
        socket.create_connection(("1.1.1.1", 443), timeout=3)
    """)
    assert not r.ok
    assert "Network is unreachable" in r.stderr or "OSError" in r.stderr


def test_no_dns():
    r = run("import socket; socket.gethostbyname('example.com')")
    assert not r.ok
    assert "gaierror" in r.stderr


def test_host_secrets_not_visible(monkeypatch):
    monkeypatch.setenv("INFERENCE_API_KEY", "sk-should-never-leak")
    r = run("""
        import os
        print(sorted(os.environ))
        print(open("/proc/self/environ", "rb").read())
    """)
    assert r.ok, r.stderr
    assert "sk-should-never-leak" not in r.stdout
    assert "INFERENCE_API_KEY" not in r.stdout


def test_runs_as_non_root():
    r = run("import os; print(os.getuid(), os.getgid())")
    assert r.stdout.strip() == "10001 10001"


def test_root_fs_and_csv_are_read_only(csv_file):
    r = run("""
        for path in ["/data/input.csv", "/sandbox/harness.py", "/etc/passwd", "/usr/evil"]:
            try:
                open(path, "a").write("x")
                print("WROTE", path)
            except OSError as e:
                print("blocked", path, type(e).__name__)
    """, csv_file)
    assert r.ok, r.stderr
    assert "WROTE" not in r.stdout
    assert r.stdout.count("blocked") == 4


def test_no_privilege_escalation():
    # no-new-privileges + cap-drop ALL: setuid binaries can't raise privileges.
    r = run("""
        import subprocess
        print(subprocess.run(["su", "-c", "id"], capture_output=True, text=True, input="").returncode)
        print(open("/proc/self/status").read())
    """)
    assert "CapEff:\t0000000000000000" in r.stdout
    assert "NoNewPrivs:\t1" in r.stdout


def test_timeout_kills_infinite_loop():
    r = run("while True: pass")
    assert r.timed_out
    assert not r.ok


def test_memory_limit():
    r = run("x = bytearray(2 * 1024**3); print('allocated')")
    assert not r.ok
    assert "allocated" not in r.stdout
    assert "memory limit" in r.stderr


def test_fork_bomb_is_contained():
    r = run("""
        import os
        n = 0
        try:
            while True:
                if os.fork() == 0:
                    import time; time.sleep(30)
                n += 1
        except OSError as e:
            print("fork stopped after", n, type(e).__name__)
    """)
    assert "fork stopped after" in r.stdout
    assert int(r.stdout.split()[3]) < int(config.SANDBOX_PIDS_LIMIT)


def test_tmp_is_size_capped():
    r = run("""
        try:
            with open("/tmp/big", "wb") as f:
                for _ in range(200): f.write(b"0" * 1024**2)
            print("WROTE 200MB")
        except OSError as e:
            print("blocked", type(e).__name__)
    """)
    assert "WROTE" not in r.stdout
    assert "blocked" in r.stdout


def test_container_is_destroyed_after_run():
    run("print('hi')")
    left = subprocess.run(["docker", "ps", "-aq", "--filter", "name=csv-sbx-"],
                          capture_output=True, text=True).stdout.strip()
    assert left == ""


def test_attacker_payload_is_contained(monkeypatch, csv_file):
    from app.containment import run_attack
    monkeypatch.setenv("SOME_HOST_TOKEN", "tok-should-never-leak-123")
    _, r, v = run_attack(csv_file)
    assert "SOME_HOST_TOKEN" in v["secrets_on_host"]
    assert v["leaked"] == []
    for attack in ["HTTP exfiltration", "raw TCP", "DNS lookup", "Docker daemon", "modify the uploaded CSV",
                   "persistent backdoor", "become root", "find .env"]:
        assert any(line.startswith("BLOCKED") and attack in line for line in r.stdout.splitlines()), attack
