"""Orchestrator tests with a scripted fake model (deterministic), real sandbox underneath.

Run: pytest -v tests/test_agent.py
"""
import json
from types import SimpleNamespace as NS

import pytest

from app import agent, config


class FakeClient:
    """Plays back scripted replies and records every request the agent sends."""

    def __init__(self, replies):
        self.replies, self.requests = list(replies), []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs)))  # snapshot, messages list keeps mutating
        return NS(choices=[NS(message=self.replies.pop(0))])


def code_call(code, id="c1"):
    fn = NS(name="run_python", arguments=json.dumps({"code": code}))
    return NS(content="", tool_calls=[NS(id=id, function=fn)])


def answer(text):
    return NS(content=text, tool_calls=None)


@pytest.fixture
def csv_file(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("a,b\n1,2\n3,4\n")
    return str(p)


def test_failed_run_feeds_traceback_back_and_model_repairs(csv_file):
    client = FakeClient([
        code_call("import pandas as pd\nprint(pd.read_csv('/data/input.csv')['c'].sum())"),  # KeyError
        code_call("import pandas as pd\nprint(pd.read_csv('/data/input.csv')['b'].sum())", id="c2"),
        answer("b sums to 6"),
    ])
    events = list(agent.analyze(csv_file, "sum of b?", client))

    results = [e for e in events if e["type"] == "result"]
    assert [r["ok"] for r in results] == [False, True]
    assert results[1]["stdout"].strip() == "6"
    # The second request must carry the traceback of the first run.
    tool_msg = client.requests[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and "KeyError" in tool_msg["content"]
    assert events[-1] == {"type": "answer", "content": "b sums to 6"}


def test_repair_budget_removes_tool(csv_file):
    bad = "raise RuntimeError('boom')"
    client = FakeClient([code_call(bad, id=f"c{i}") for i in range(config.MAX_REPAIR_ATTEMPTS)]
                        + [answer("I could not compute it")])
    events = list(agent.analyze(csv_file, "q", client))

    assert sum(e["type"] == "code" for e in events) == config.MAX_REPAIR_ATTEMPTS
    assert "tools" in client.requests[0]
    assert "tools" not in client.requests[-1]  # final call can only answer
    assert events[-1]["content"] == "I could not compute it"


def test_malformed_tool_call_is_reported_not_crashed(csv_file):
    broken = NS(content="", tool_calls=[NS(id="x", function=NS(name="run_python", arguments="{not json"))])
    client = FakeClient([broken, answer("ok")])
    events = list(agent.analyze(csv_file, "q", client))

    assert events[0]["type"] == "error"
    assert "Bad tool call" in client.requests[1]["messages"][-1]["content"]
    assert events[-1]["content"] == "ok"
