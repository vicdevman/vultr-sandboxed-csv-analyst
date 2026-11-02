"""Containment demo (CLI): run the attacker payload in the sandbox, then check the host's secrets didn't leak.

Run: python -m scripts.containment_demo
"""
import sys

from app.containment import run_attack

sys.stdout.reconfigure(encoding="utf-8")
_, r, v = run_attack("samples/hostile_expenses.csv")
assert v["secrets_on_host"], "put a real INFERENCE_API_KEY in .env first, so there is something to steal"
print(f"Host holds {len(v['secrets_on_host'])} secret(s): {', '.join(v['secrets_on_host'])}")
print("Attacker payload ran inside the sandbox:\n")
print(r.stdout or r.stderr)
print(f"Attempts blocked: {v['blocked']} / {v['attempts']}")
print(f"Host secrets found in sandbox output: {len(v['leaked'])} {v['leaked'] or ''}")
print("!!! CONTAINMENT FAILED !!!" if v["leaked"] else "Contained. Container destroyed after the run.")
