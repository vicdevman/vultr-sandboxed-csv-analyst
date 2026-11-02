"""Step 0 smoke test: is the endpoint reachable, is MODEL listed, and does a tool call round-trip work?

Run: python scripts/smoke_inference.py
Works against any OpenAI-compatible base_url (OpenRouter locally, Vultr Serverless Inference in prod).
"""
import json
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(base_url=os.environ["INFERENCE_BASE_URL"], api_key=os.environ["INFERENCE_API_KEY"])
model = os.environ["MODEL"]

# 1. Model listed?
ids = {m.id for m in client.models.list()}
print(f"[models] {len(ids)} models at {client.base_url}; {model!r} listed: {model in ids}")

# 2. Tool call round-trip: model must call add(), we return the result, model answers.
tools = [{
    "type": "function",
    "function": {
        "name": "add",
        "description": "Add two integers.",
        "parameters": {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        },
    },
}]
messages = [{"role": "user", "content": "What is 1234 + 5678? Use the add tool."}]
r = client.chat.completions.create(model=model, messages=messages, tools=tools)
msg = r.choices[0].message
assert msg.tool_calls, f"no tool call returned: {msg.content!r}"
call = msg.tool_calls[0]
args = json.loads(call.function.arguments)
print(f"[tool_call] {call.function.name}({args})")

messages.append(msg.model_dump(exclude_none=True))
messages.append({"role": "tool", "tool_call_id": call.id, "content": str(args["a"] + args["b"])})
r2 = client.chat.completions.create(model=model, messages=messages, tools=tools)
print(f"[answer] {r2.choices[0].message.content!r}")
