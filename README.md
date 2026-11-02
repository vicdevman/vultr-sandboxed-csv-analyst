# Sandboxed CSV Analyst

Upload a CSV and ask a question in plain English. The model writes Python to answer it, the code runs in a
throwaway locked-down container, and the model explains the real output, charts included. If the code fails,
the traceback goes back to the model so it can fix its own code (with a retry limit).

Built for the [Vultr: Agent Rush](https://lablab.ai/ai-hackathons/vultr-hackathon) hackathon, Challenge 1
"Blast Radius Zero": the agent runs code it wrote itself, and every run is contained.

## How it works

```
 Browser ──upload CSV + question──▶ FastAPI app (on the Vultr VM)
                                      │
                                      │ 1. chat completion with a run_python tool
                                      ▼
                             Vultr Serverless Inference
                                      │
                                      │ 2. tool call: Python code
                                      ▼
                     docker run  (fresh container per run, gVisor runtime)
                     no network · read-only fs · non-root · no capabilities
                     memory / CPU / process / time limits · CSV mounted read-only
                                      │
                                      │ 3. stdout, stderr, charts (one JSON line)
                                      ▼
                     back to the model ── error? retry with traceback (max 3)
                                      │
                                      ▼ 4. final answer + charts, streamed to the browser
```

The app runs on the host and starts the containers itself. It is **not** run in a container with
`docker.sock` mounted, because that would give the agent's code a path to root on the host.

## Vultr services used

| Service | Role |
|---|---|
| **Vultr Cloud Compute** | Hosts the web app and runs the sandbox containers |
| **Vultr Serverless Inference** | The model (OpenAI-compatible API with tool calling), default `deepseek-v4.1-flash-1017` |

Any OpenAI-compatible endpoint works for local development (e.g. OpenRouter or Groq). Switching providers is a
`.env` change, not a code change.

## Security model

The model is treated as potentially hijacked: the CSV itself may contain prompt injection. The sandbox is
designed to hold even if the model does everything an attacker tells it to.

| Control | How |
|---|---|
| No network | `--network none` (no internet, no DNS, no access to the host) |
| No secrets inside | No environment variables are passed in; the API key stays on the host |
| Read-only | Read-only root filesystem; the CSV is mounted read-only; only `/tmp` is writable (64 MB, in memory) |
| No privileges | Runs as uid 10001, `--cap-drop ALL`, `no-new-privileges` |
| Resource limits | 512 MB memory (no swap), 1 CPU, 128 processes, 20 s timeout with a host-side kill |
| Clean lifecycle | One container per run, removed afterwards |
| Kernel isolation | On the VM, gVisor (`runsc`) puts a user-space kernel between the code and the host kernel |

A prompt guard in the system prompt is a second, weaker layer. The **Containment test** button skips the model
and runs 10 attacks (environment dump, secret hunting, HTTP/TCP/DNS exfiltration, `docker.sock`, writing files,
privilege escalation) directly in the sandbox. The host then checks the output for the real values of its own
secrets.

## Run locally

Requires Python 3.11+, Docker, and an API key for an OpenAI-compatible endpoint with tool calling.

```bash
git clone https://github.com/vicdevman/vultr-sandboxed-csv-analyst.git
cd vultr-sandboxed-csv-analyst

python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

docker build -t csv-analyst-sandbox:latest sandbox

cp .env.example .env        # then fill in INFERENCE_API_KEY (and MODEL if needed)
python -m scripts.smoke_inference   # checks the endpoint and a tool-call round-trip

python -m uvicorn app.main:app --port 8000
```

Open http://localhost:8000, upload `samples/sales.csv`, and ask something like
*"Total revenue by region, with a bar chart."*

## Deploy on a Vultr VM

For Ubuntu. Run as a regular user with sudo.

**1. Docker**
```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
```

**2. gVisor**
```bash
sudo apt-get update && sudo apt-get install -y apt-transport-https ca-certificates curl gnupg
curl -fsSL https://gvisor.dev/archive.key | sudo gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" \
  | sudo tee /etc/apt/sources.list.d/gvisor.list > /dev/null
sudo apt-get update && sudo apt-get install -y runsc
sudo runsc install                 # registers runsc in /etc/docker/daemon.json
sudo systemctl restart docker
docker run --rm --runtime=runsc hello-world
```

**3. App**
```bash
sudo apt-get install -y python3-venv git
git clone https://github.com/vicdevman/vultr-sandboxed-csv-analyst.git
cd vultr-sandboxed-csv-analyst
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
docker build -t csv-analyst-sandbox:latest sandbox
cp .env.example .env
```

In `.env`, point inference at Vultr and turn on gVisor:
```bash
INFERENCE_BASE_URL=https://api.vultrinference.com/v1
INFERENCE_API_KEY=<your Vultr Serverless Inference key>
MODEL=deepseek-v4.1-flash-1017
SANDBOX_RUNTIME=runsc
```

**4. Verify and run**
```bash
.venv/bin/python -m pytest -q      # the sandbox tests now run under gVisor
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Allow port 8000 in the Vultr firewall (or put a reverse proxy with HTTPS in front).

## Configuration

All settings live in `.env` (see [.env.example](.env.example)).

| Variable | Default | Meaning |
|---|---|---|
| `INFERENCE_BASE_URL` | – | OpenAI-compatible endpoint |
| `INFERENCE_API_KEY` | – | API key (never enters the sandbox) |
| `MODEL` | – | Model id; must support tool calling |
| `SANDBOX_RUNTIME` | `runc` | `runsc` for gVisor |
| `SANDBOX_TIMEOUT_SECONDS` | `20` | Per-run time limit |
| `SANDBOX_MEMORY` | `512m` | Memory limit (swap disabled) |
| `SANDBOX_CPUS` | `1` | CPU limit |
| `SANDBOX_PIDS_LIMIT` | `128` | Max processes |
| `MAX_REPAIR_ATTEMPTS` | `3` | Failed runs before the model must answer without code |

## Command-line tools

```bash
python -m scripts.ask samples/sales.csv "Which region had the highest revenue?"
python -m scripts.containment_demo       # 10 attacks, verdict decided on the host
python -m pytest -q                      # sandbox hardening, repair loop, containment
```

`samples/hostile_expenses.csv` hides a prompt injection in its `note` column. Try it in the UI with the prompt
guard on and off.

## Project layout

```
app/        FastAPI server, agent loop, sandbox runner, containment check
sandbox/    Sandbox image (pandas, numpy, matplotlib baked in) and the in-container harness
static/     Single-file web UI
samples/    Demo CSVs and the attacker payload
scripts/    CLI tools
tests/      pytest suite (needs Docker and the sandbox image)
```

## License

[MIT](LICENSE)
