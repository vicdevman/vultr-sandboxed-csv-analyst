# vultr-sandboxed-csv-analyst

Reference build + lablab.ai tutorial for the **Vultr: Agent Rush** hackathon
(https://lablab.ai/ai-hackathons/vultr-hackathon), Challenge 1 "Blast Radius Zero", Pattern A
(model writes code → runs in isolated sandbox → real output → model explains; errors feed back).

The user is the DevRel for this hackathon. Two goals, equal weight:
1. Ship a working, submission-grade reference project + tutorial (`tutorials/en/vultr-sandboxed-csv-analyst.mdx`).
2. Be able to answer any participant's technical question — so explain *why* behind every choice.

Work step by step, verify each step actually runs before moving on. No guessing about APIs or model
names — check live endpoints. Full brief, research and sources: `docs/BRIEF.md`. Progress: `docs/STATUS.md`
(keep it updated at the end of each step).

## What it builds
Web app: upload a CSV, ask a question → model (via tool calling) writes Python → runs in a throwaway,
locked-down Docker container → stdout + chart files come back → model explains. Failed runs feed the
traceback back to the model (bounded retries). Demo includes a prompt-injected CSV that tries to
exfiltrate secrets / reach the network and gets blocked (the required "containment moment").

## Locked decisions
- **Backend:** Python 3.11 + FastAPI, OpenAI Python SDK pointed at any OpenAI-compatible `base_url`.
- **Inference:** local dev uses OpenRouter (or Groq); prod uses Vultr Serverless Inference
  (`https://api.vultrinference.com/v1`). Switching = change `INFERENCE_BASE_URL`, `INFERENCE_API_KEY`,
  `MODEL` in `.env`. Never hard-code a model.
  - Default model `deepseek-v4.1-flash-1017` (Vultr id) / `deepseek/deepseek-v4.1-flash-1017` (OpenRouter id) — same model both sides.
  - Vultr's live `/v1/models` (public, no auth) lists 12 text models with `tools: true` (deepseek-v4.1-flash-1017,
    glm-5.2, glm-5.3, glm-5.3-flash, qwen3.8-27b, qwen3.8-flash-next, mimo-v2.6-pro/-flash, minimax-m3.1-flash,
    muse-glimmer-30b, nemotron-3-nano-omni-30b-a3b-reasoning, raon-1-mini-preview). Kimi K2 is NOT available
    (older Vultr docs say tool calling is kimi-only — outdated).
- **Sandbox:** Docker, hardened: `--rm --network none --read-only --cap-drop ALL
  --security-opt no-new-privileges --user <non-root> --memory --cpus --pids-limit --tmpfs /tmp` + host-side
  hard timeout + kill. pandas/matplotlib baked into the image (no pip at runtime). One container per run, destroyed after.
  - On the Vultr VM add gVisor via `SANDBOX_RUNTIME=runsc` (no KVM needed). Locally (Docker Desktop/Windows) use default `runc`.
  - Microsandbox rejected as the default: needs KVM; Vultr standard VMs historically lack nested virt; Windows support is preview.
    Optional extra only if `/dev/kvm` exists on the VM.
- **App runs on the host, NOT in a container with docker.sock mounted** (that would hand the agent host root —
  contradicts "Blast Radius Zero"). Same code runs on Windows locally and Ubuntu on Vultr.
- **Secrets stay on the host.** The sandbox receives only the CSV (read-only mount) and the code. No env vars passed in.

## Environment notes (this Windows machine)
- `python` = 3.11.9 (added to user PATH; `py` also works). Use a venv: `.venv`.
- Node 24, Git, Docker Desktop 29.8 (linux engine, runc) available.
- Shell: PowerShell primary, Git Bash available.

## Deadlines
- Hackathon online build: Nov 3–8, 2026 (exact cutoff time "TBA" on page — treat Nov 8 as the end).
- Vultr $200 credits arrive at kickoff Nov 3 (Billing → Hackathon Promotion Page; never-used email).
- **Publish tutorial by Nov 4–5.**
