"""Bounded diagnostics of hosted-model calls, recorded in the trace and never used to answer (preparation for the
development model comparison).

- **Settings, requested and reported, kept apart** (``settings``): the model, reasoning effort and output cap the
  controller sent, and those the response reports. A field the response does not carry is recorded as "not reported";
  a reasoning effort the request did not send is recorded as not sent, so the provider's default applied.
- **A response that did not finish** (``incomplete_output``): its visible text's length, a bounded head and tail, the
  share of whitespace, the longest run of one repeated character and of one repeated line, the trailing whitespace,
  and the JSON field open at the cutoff. The text is described, never parsed into an answer: the controller rejects the response before parsing
  exactly as before (``LiveController._structured``).
  - **The cause** is "unknown" unless the visible text itself establishes it. Token usage alone never does (Live check
    of the v12 routing extraction: three of four cut-off routing calls returned 912 to 1,168 visible tokens whose
    content was not kept, so their cause could not be told).
  - **The open field** is "established" only when the text is a valid JSON prefix and the cutoff falls inside a value
    whose key is known; otherwise it is "uncertain", with the reason.

No request input, instruction or key is recorded: only the response's own visible output, bounded.
"""

from __future__ import annotations

import json
import re
from typing import Any

NOT_REPORTED = "not reported"
NOT_SENT = "not sent (the provider's default applies)"
EXCERPT = 300  # characters kept from each end of a cut-off response's visible text
REPEAT_MIN = 200  # a run this long (characters) that reaches the cutoff and covers half the text is called repetition


def settings(model: str, request: dict[str, Any], max_output_tokens: int, resp: dict[str, Any] | None) -> dict[str, Any]:
    """The model, reasoning effort and output cap requested, and those the response reports (None: no response)."""
    sent = request.get("reasoning")
    out: dict[str, Any] = {"requested": {
        "model": model, "max_output_tokens": max_output_tokens,
        "reasoning_effort": sent["effort"] if isinstance(sent, dict) and sent.get("effort") else NOT_SENT}}
    if resp is not None:
        got = resp.get("reasoning")
        cap = resp.get("max_output_tokens")
        out["reported"] = {
            "model": resp.get("model") or NOT_REPORTED,
            "max_output_tokens": cap if isinstance(cap, int) and not isinstance(cap, bool) else NOT_REPORTED,
            "reasoning_effort": got["effort"] if isinstance(got, dict) and got.get("effort") else NOT_REPORTED}
    return out


def visible_output(resp: dict[str, Any]) -> str:
    """The response's visible output, in order: message text and function-call arguments (not reasoning)."""
    parts = []
    for item in resp.get("output", []) or []:
        if item.get("type") == "message":
            parts += [c.get("text", "") for c in item.get("content", []) or [] if c.get("type") == "output_text"]
        elif item.get("type") == "function_call":
            parts.append(str(item.get("arguments") or ""))
    return "".join(parts)


def _shown(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)[1:-1]  # whitespace and control characters made visible


def _char_run(text: str) -> dict[str, Any] | None:
    best = None
    for m in re.finditer(r"(.)\1*", text, re.S):
        if best is None or len(m.group(0)) > best[1]:
            best = (m.group(1), len(m.group(0)), m.start())
    if best is None:
        return None
    char, length, start = best
    return {"char": _shown(char), "length": length, "start": start, "ends_at_cutoff": start + length == len(text)}


def _line_run(text: str) -> dict[str, Any] | None:
    lines = text.split("\n")
    best, i = None, 0
    while i < len(lines):
        j = i
        while j + 1 < len(lines) and lines[j + 1] == lines[i]:
            j += 1
        if j > i and (best is None or j - i + 1 > best[1]):
            best = (i, j - i + 1)
        i = j + 1
    if best is None:
        return None
    first, count = best
    line = lines[first]
    return {"line": _shown(line[:80]), "count": count, "chars": count * (len(line) + 1),
            "ends_at_cutoff": first + count == len(lines)}


# -- the JSON field open at the cutoff: a strict scan of the text as a JSON prefix ----------------------------------
_NUMBER_RE = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")
_NUMBER_PREFIX_RE = re.compile(r"-?(?:0|[1-9]\d*)?(?:\.\d*)?(?:[eE][+-]?\d*)?")
_LITERALS = ("true", "false", "null")
_ESCAPES = set('"\\/bfnrtu')


def _path(stack: list[dict[str, Any]]) -> str:
    out = ""
    for f in stack:
        if f["t"] == "o" and f["key"] is not None:
            out += ("." if out else "") + f["key"]
        elif f["t"] == "a":
            out += f"[{f['idx']}]"
    return out


def open_json_field(text: str) -> dict[str, Any]:
    """The JSON field whose value the text was writing when it stopped: {path, certainty, reason}."""
    def uncertain(reason: str, path: str | None = None) -> dict[str, Any]:
        return {"path": path, "certainty": "uncertain", "reason": reason}

    stack: list[dict[str, Any]] = []  # frames: t ("o" object, "a" array), key, idx, want
    want = "value"  # at the top level: one value
    done = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if done:
            return uncertain(f"not a JSON prefix: text after the complete top-level value, at offset {i}")
        frame = stack[-1] if stack else None
        if ch == '"':  # a string: a key or a value
            j, esc = i + 1, False
            while j < n:
                c = text[j]
                if esc:
                    if c not in _ESCAPES or (c == "u" and not re.fullmatch(r"[0-9a-fA-F]*", text[j + 1:j + 5])):
                        return uncertain(f"not a JSON prefix: a bad escape at offset {j}")
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    break
                elif ord(c) < 0x20:
                    return uncertain(f"not a JSON prefix: a control character inside a string at offset {j}")
                j += 1
            is_key = frame is not None and frame["t"] == "o" and want in ("key", "key_or_end")
            if j >= n:  # the cutoff falls inside this string
                if is_key:
                    return uncertain("the cutoff falls inside a key, so the field is not known", _path(stack) or None)
                if want not in ("value", "value_or_end"):
                    return uncertain(f"not a JSON prefix: a string where {want} was expected")
                path = _path(stack)
                if frame is None:
                    return uncertain("the cutoff falls inside a top-level string")
                if frame["t"] == "o" and frame["key"] is None:
                    return uncertain("the cutoff falls inside a value whose key is not known")
                return {"path": path, "certainty": "established",
                        "reason": "the text is a valid JSON prefix and stops inside this field's string value"}
            if is_key and frame is not None:
                frame["key"] = json.loads(text[i:j + 1])
                want = "colon"
            elif want in ("value", "value_or_end"):
                want = _after_value(stack)
                done = not stack
            else:
                return uncertain(f"not a JSON prefix: a string where {want} was expected, at offset {i}")
            i = j + 1
            continue
        if ch == ":":
            if not (frame and frame["t"] == "o" and want == "colon"):
                return uncertain(f"not a JSON prefix: an unexpected ':' at offset {i}")
            want = "value"
        elif ch == ",":
            if not (frame and want == "comma_or_end"):
                return uncertain(f"not a JSON prefix: an unexpected ',' at offset {i}")
            if frame["t"] == "o":
                frame["key"], want = None, "key"
            else:
                frame["idx"] += 1
                want = "value"
        elif ch in "}]":
            t = "o" if ch == "}" else "a"
            ok_end = frame is not None and frame["t"] == t and (
                want == "comma_or_end" or (want == "key_or_end" and t == "o") or (want == "value_or_end" and t == "a"))
            if not ok_end:
                return uncertain(f"not a JSON prefix: an unexpected '{ch}' at offset {i}")
            stack.pop()
            want = _after_value(stack)
            done = not stack
        elif ch in "{[":
            if want not in ("value", "value_or_end"):
                return uncertain(f"not a JSON prefix: an unexpected '{ch}' at offset {i}")
            if ch == "{":
                stack.append({"t": "o", "key": None, "idx": 0})
                want = "key_or_end"
            else:
                stack.append({"t": "a", "key": None, "idx": 0})
                want = "value_or_end"
        elif want == "key_or_end" and frame is not None and frame["t"] == "o":
            return uncertain(f"not a JSON prefix: a key must be a string, at offset {i}")
        else:  # a number or a literal
            if want not in ("value", "value_or_end"):
                return uncertain(f"not a JSON prefix: an unexpected '{ch}' at offset {i}")
            m = re.compile(r"[^\s,\]}]*").match(text, i)
            tok = m.group(0) if m else ""
            end = i + len(tok)
            cut = end >= n
            ok = (_NUMBER_PREFIX_RE.fullmatch(tok) or any(lit.startswith(tok) for lit in _LITERALS)) if cut else \
                (_NUMBER_RE.fullmatch(tok) or tok in _LITERALS)
            if not ok:
                return uncertain(f"not a JSON prefix: '{tok[:20]}' is not a JSON value, at offset {i}")
            if cut:
                if frame is None or (frame["t"] == "o" and frame["key"] is None):
                    return uncertain("the cutoff falls inside a value whose key is not known")
                return {"path": _path(stack), "certainty": "established",
                        "reason": "the text is a valid JSON prefix and stops inside this field's value"}
            want = _after_value(stack)
            done = not stack
            i = end
            continue
        i += 1
    if not text.strip():
        return uncertain("no visible text")
    if done:
        return uncertain("the cutoff falls after the complete top-level value (in trailing whitespace)")
    path = _path(stack)
    where = {"key": "before a key", "key_or_end": "before a key", "colon": "after a key, before its colon",
             "value": "after a key or separator, before a value", "value_or_end": "before a value",
             "comma_or_end": "after a value, before the next separator"}.get(want, "between tokens")
    return uncertain(f"the cutoff falls between tokens ({where}), so no field's value was being written",
                     path or None)


def _after_value(stack: list[dict[str, Any]]) -> str:
    return "comma_or_end" if stack else "done"


def incomplete_output(resp: dict[str, Any]) -> dict[str, Any]:
    """A bounded description of a response that did not finish (status not "completed", or incomplete details)."""
    text = visible_output(resp)
    n = len(text)
    char_run, line_run = _char_run(text), _line_run(text)
    out: dict[str, Any] = {
        "visible_chars": n,
        "head": text[:EXCERPT],
        "tail": text[max(EXCERPT, n - EXCERPT):],  # never overlaps the head
        "whitespace_share": round(sum(c.isspace() for c in text) / n, 3) if n else None,
        "longest_char_run": char_run,
        "longest_line_run": line_run,
        "trailing_whitespace_chars": n - len(text.rstrip()),
        "open_json_field": open_json_field(text),
    }
    trailing = out["trailing_whitespace_chars"]
    if n == 0:
        cause, why = "unknown", "no visible text was returned; token usage alone does not establish a cause"
    elif char_run and char_run["ends_at_cutoff"] and char_run["length"] >= max(REPEAT_MIN, n / 2):
        cause = "repetition at the cutoff"
        why = (f"the last {char_run['length']} of {n} visible characters repeat one character "
               f"(\"{char_run['char']}\") up to the cutoff")
    elif trailing >= max(REPEAT_MIN, n / 2):
        cause = "whitespace at the cutoff"
        why = f"the last {trailing} of {n} visible characters are whitespace, up to the cutoff"
    elif line_run and line_run["ends_at_cutoff"] and line_run["count"] >= 5 and \
            line_run["chars"] >= max(REPEAT_MIN, n / 2):
        cause = "repetition at the cutoff"
        why = (f"the last {line_run['count']} lines ({line_run['chars']} of {n} visible characters) repeat one line "
               "up to the cutoff")
    else:
        cause, why = "unknown", "the visible text does not establish a cause, and token usage alone does not"
    out["cause"], out["cause_evidence"] = cause, why
    return out
