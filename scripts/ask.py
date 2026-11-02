"""CLI for the agent: python -m scripts.ask samples/sales.csv "Which region sold most?" [--no-guard]"""
import sys

from app.agent import analyze

sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252 and choke on model output
guard = "--no-guard" not in sys.argv

for ev in analyze(sys.argv[1], sys.argv[2], guard=guard):
    if ev["type"] == "code":
        print(f"\n--- code (attempt {ev['attempt']}) ---\n{ev['content']}")
    elif ev["type"] == "result":
        print(f"--- result ok={ev['ok']} exit={ev['exit_code']} timed_out={ev['timed_out']} "
              f"files={[f['name'] for f in ev['files']]} ---\n{ev['stdout']}{ev['stderr'][-1500:]}")
    else:
        print(f"\n=== {ev['type']} ===\n{ev['content']}")
