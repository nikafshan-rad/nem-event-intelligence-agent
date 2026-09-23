"""SYNTHETIC stand-in for a hosted model (tests only). It returns Responses-API-shaped dicts, reads the
function_call_output items it is given (as a model would) and never touches the network."""

from __future__ import annotations

import copy
import itertools
import json
from typing import Any

_ids = itertools.count(1)


def msg(text: str) -> dict[str, Any]:
    return {"id": f"resp_{next(_ids)}", "output": [{"type": "message", "role": "assistant",
                                                     "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": 100, "output_tokens": 50}}


def calls(*items: tuple[str, dict[str, Any] | str]) -> dict[str, Any]:
    out = []
    for name, args in items:
        out.append({"type": "function_call", "id": f"fc_{next(_ids)}", "call_id": f"call_{next(_ids)}", "name": name,
                    "arguments": args if isinstance(args, str) else json.dumps(args), "status": "completed"})
    return {"id": f"resp_{next(_ids)}", "output": out, "usage": {"input_tokens": 120, "output_tokens": 40}}


def outputs(kw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """call_id -> parsed tool payload, from the request input."""
    res = {}
    for it in kw.get("input", []):
        if isinstance(it, dict) and it.get("type") == "function_call_output":
            res[it["call_id"]] = json.loads(it["output"])
    return res


class FakeModel:
    def __init__(self, route: dict[str, Any], tool_turns: list[list[tuple[str, Any]]], report_fn: Any,
                 repair_fn: Any = None) -> None:
        self.route, self.tool_turns, self.report_fn, self.repair_fn = route, list(tool_turns), report_fn, repair_fn
        self.requests: list[dict[str, Any]] = []
        self.issued: list[dict[str, Any]] = []

    def create(self, **kw: Any) -> dict[str, Any]:
        self.requests.append(copy.deepcopy(kw))  # snapshot: the controller keeps appending to its input list
        fmt = (kw.get("text") or {}).get("format", {}).get("name")
        if fmt == "RouteDecision":
            return msg(json.dumps(self.route))
        if fmt == "ModelReport":
            last = kw["input"][-1]
            if self.repair_fn and isinstance(last, dict) and "failed independent validation" in str(last.get("content")):
                return msg(json.dumps(self.repair_fn(kw)))
            return msg(json.dumps(self.report_fn(kw)))
        if self.tool_turns:
            resp = calls(*self.tool_turns.pop(0))
            self.issued += resp["output"]
            return resp
        return msg("done")
