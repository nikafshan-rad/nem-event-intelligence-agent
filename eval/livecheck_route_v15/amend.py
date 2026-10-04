"""Amendment 1 of the routing-only Live check of route contract v15 (AMENDMENT_1.md): the amended gold and the
extraction gold, built mechanically from the two independent agents' records. Offline; no model call.

- **`GOLD_AMENDED.json`:** `GOLD.json` (kept unchanged as the original gold) with D08 re-resolved:
  - its acceptable outcomes are those both independent agents judge genuinely acceptable (`D08_WRITER.json`,
    `D08_REVIEWER.json`), with their rationales;
  - its primary outcome is the writer's, if both accept it;
  - a resolved reading remains only if both accept `resolved`.

  The owner's earlier instruction accepting the demand reading is withdrawn.
- **`EXTRACTION_GOLD.json`:** what a careful reader's extraction contains, combined from the writer's and the
  reviewer's independent records (`EXTRACTION_WRITER.json`, `EXTRACTION_REVIEWER.json`):
  - **labels** (region, domain, operation, run rule, maximum, whether a cutoff is stated) must be equal;
  - **acceptable sets** (intents, local dates, scope kinds) are what both accept: their intersection, which must not be
    empty. Where the two intent sets differ, intent is recorded, not assessed (an item is assessed only where both
    authors agree on it);
  - **key words** are required only if both authors require them: the intersection of their word tokens;
  - **anchors** are the union of both, and no author's request anchor may lie on the other's excluded or unsupported
    anchors;
  - **the extraction gold must also agree** with the amended gold of the same question.

Any disagreement is listed and nothing is written: it goes to the owner, and this script never resolves it.

Usage: python eval/livecheck_route_v15/amend.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
OUTCOMES = {"resolved", "clarify_unsupported", "clarify_which_forecast", "clarify_mixed", "refusal",
            "event_review_unsupported", "event_review_unclear"}
LABELS = ("region", "domain", "operation", "run_rule")
SETS = ("intents", "local_dates", "scope_kinds")
KEYS = ("scope_key_words", "run_key_words", "half_hour_key_words", "cutoff_key_words")
TOKEN = re.compile(r"[A-Za-z0-9:'’+.\-]+")


def _load(name: str) -> Any:
    return json.loads((HERE / name).read_text())


def tokens(words: list[str]) -> list[str]:
    """The word tokens of key words, lower-cased, in first-seen order (``"4 August 2026"`` gives three tokens)."""
    out: list[str] = []
    for w in words:
        for t in TOKEN.findall(w.lower()):
            t = t.strip(".")
            if t and t not in out:
                out.append(t)
    return out


def _spans(text: str, q: str) -> list[tuple[int, int]]:
    out, i = [], q.find(text) if text else -1
    while i >= 0:
        out.append((i, i + len(text)))
        i = q.find(text, i + 1)
    return out


def _overlap(a: str, b: str, q: str) -> bool:
    return any(x[0] < y[1] and y[0] < x[1] for x in _spans(a, q) for y in _spans(b, q))


def amended_gold(gold: dict[str, Any], w: dict[str, Any], r: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """GOLD.json with D08 re-resolved by both independent agents."""
    problems = []
    for who, rec in (("writer", w), ("reviewer", r)):
        if rec.get("config") != "D08" or not set(rec.get("acceptable_outcomes") or []) <= OUTCOMES or \
                rec.get("outcome") not in OUTCOMES or not rec.get("rationale"):
            problems.append(f"D08: the {who}'s final record is not valid")
    both = [o for o in w.get("acceptable_outcomes") or [] if o in (r.get("acceptable_outcomes") or [])]
    if not both:
        problems.append(f"D08: no outcome both agents accept (writer {w.get('acceptable_outcomes')}, reviewer "
                        f"{r.get('acceptable_outcomes')})")
    if w.get("outcome") != r.get("outcome"):
        problems.append(f"D08: primary outcome: writer {w.get('outcome')}, reviewer {r.get('outcome')} (reported)")
    out = json.loads(json.dumps(gold))
    for g in out["cases"]:
        if g["config"] != "D08":
            continue
        outcome = w.get("outcome") if w.get("outcome") in both else (both[0] if both else None)
        g["outcome"] = outcome
        g["acceptable_outcomes"] = [outcome, *[o for o in both if o != outcome]] if outcome else []
        if "resolved" not in both:  # no resolved reading remains: no request may be bound, no demand tool used
            g.update(resolved_reading=None, intents=[], operation=None, scope=None, run=None,
                     request_anchors=[], demand_forecast_tools="not_used")
        g["amendment"] = {
            "by": "AMENDMENT_1.md: the owner withdrew the earlier instruction accepting the demand reading; D08's "
                  "acceptable outcomes are those both independent agents judge genuinely acceptable",
            "original_acceptable_outcomes": ["clarify_which_forecast", "resolved"],
            "writer": {k: w.get(k) for k in ("outcome", "acceptable_outcomes", "rationale")},
            "reviewer": {k: r.get(k) for k in ("outcome", "acceptable_outcomes", "rationale")}}
    out["generated_by"] = "eval/livecheck_route_v15/amend.py (Amendment 1), from GOLD.json"
    return out, problems


def combine(cfg: str, q: str, w: dict[str, Any], r: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """One question's extraction gold from the writer's and the reviewer's records, and every disagreement."""
    bad: list[str] = []
    out: dict[str, Any] = {"config": cfg}
    for k in LABELS:
        if w.get(k) != r.get(k):
            bad.append(f"{cfg}: {k}: writer {w.get(k)!r}, reviewer {r.get(k)!r}")
        out[k] = w.get(k)
    for k in SETS:
        a, b = list(w.get(k) or []), list(r.get(k) or [])
        out[k] = [x for x in a if x in b]
        if (a or b) and not out[k]:
            bad.append(f"{cfg}: {k}: writer {a}, reviewer {b}, nothing in common")
    # an item is assessed only where both authors agree on it: differing intent sets are recorded, not assessed
    out["intents_agreed"] = set(w.get("intents") or []) == set(r.get("intents") or [])
    out["intents_by_author"] = {"writer": w.get("intents"), "reviewer": r.get("intents")}
    if not out["intents_agreed"]:
        bad.append(f"{cfg}: intents: writer {w.get('intents')}, reviewer {r.get('intents')}: not assessed (reported)")
    for k in KEYS:
        a, b = tokens(w.get(k) or []), tokens(r.get(k) or [])
        out[k] = [t for t in a if t in b]
    if bool(w.get("cutoff_words")) != bool(r.get("cutoff_words")):
        bad.append(f"{cfg}: cutoff stated: writer {w.get('cutoff_words')!r}, reviewer {r.get('cutoff_words')!r}")
    if out["cutoff_key_words"] == [] and (w.get("cutoff_words") or r.get("cutoff_words")):
        bad.append(f"{cfg}: a cutoff is stated, but no key word is common to both")
    wm, rm = w.get("maximum") or {}, r.get("maximum") or {}
    if bool(wm) != bool(rm) or (wm and rm and (wm.get("measure"), wm.get("window")) != (rm.get("measure"),
                                                                                   rm.get("window"))):
        bad.append(f"{cfg}: maximum: writer {wm}, reviewer {rm}")
        out["maximum"] = wm or None
    else:
        out["maximum"] = None if not wm else {
            "measure": wm["measure"], "window": wm["window"],
            "measure_key_words": [t for t in tokens(wm.get("measure_key_words") or [])
                                  if t in tokens(rm.get("measure_key_words") or [])],
            "window_key_words": [t for t in tokens(wm.get("window_key_words") or [])
                                 if t in tokens(rm.get("window_key_words") or [])]}
    for k in ("request_anchors", "excluded_anchors", "unsupported_anchors"):
        out[k] = list(dict.fromkeys([*(w.get(k) or []), *(r.get(k) or [])]))
        bad += [f"{cfg}: {k} {a!r} is not copied exactly from the question" for a in out[k] if a not in q]
    wu, ru = w.get("unsupported_anchors") or [], r.get("unsupported_anchors") or []
    if len(wu) != len(ru) or not all(any(_overlap(a, b, q) for b in ru) for a in wu):
        bad.append(f"{cfg}: unsupported anchors: writer {wu}, reviewer {ru}")
    for who, me, other in (("writer", w, r), ("reviewer", r, w)):
        for a in me.get("request_anchors") or []:
            if any(_overlap(a, x, q) for x in (other.get("excluded_anchors") or []) +
                   (other.get("unsupported_anchors") or [])):
                bad.append(f"{cfg}: the {who}'s request anchor {a!r} is excluded or unsupported in the other's record")
    out["words"] = {"writer": {k: w.get(k) for k in ("scope_words", "run_words", "half_hour_words", "cutoff_words")},
                    "reviewer": {k: r.get(k) for k in ("scope_words", "run_words", "half_hour_words", "cutoff_words")}}
    out["notes"] = {"writer": w.get("notes"), "reviewer": r.get("notes")}
    return out, bad


def consistent(x: dict[str, Any], g: dict[str, Any]) -> list[str]:
    """Disagreements between a question's extraction gold and its amended gold."""
    c, out = x["config"], []
    if x["region"] != g["region"]:
        out.append(f"{c}: region: extraction {x['region']}, gold {g['region']}")
    if x["domain"] != g["domain"]:
        out.append(f"{c}: domain: extraction {x['domain']}, gold {g['domain']}")
    if g["resolved_reading"] == "operational_demand_forecast":
        if x["operation"] != g["operation"]:
            out.append(f"{c}: operation: extraction {x['operation']}, gold {g['operation']}")
        if not set(x["scope_kinds"]) & set(g["scope"]["kinds"]):
            out.append(f"{c}: scope kinds: extraction {x['scope_kinds']}, gold {g['scope']['kinds']}")
        if x["run_rule"] != g["run"]["rule"]:
            out.append(f"{c}: run rule: extraction {x['run_rule']}, gold {g['run']['rule']}")
        if not set(x["intents"]) & set(g["intents"]):
            out.append(f"{c}: intents: extraction {x['intents']}, gold {g['intents']}")
    if bool(x["unsupported_anchors"]) != bool(g["unsupported_parts"]):
        out.append(f"{c}: unsupported: extraction {x['unsupported_anchors']}, gold {g['unsupported_parts']}")
    if bool(x["maximum"]) != bool(g["maximum"]):
        out.append(f"{c}: maximum: extraction {x['maximum']}, gold {g['maximum']}")
    return out


def build() -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    gold = _load("GOLD.json")
    amended, problems = amended_gold(gold, _load("D08_WRITER.json"), _load("D08_REVIEWER.json"))
    qs = {c["config"]: c["question"] for c in _load("cases.json")["cases"]}
    w = {c["config"]: c for c in _load("EXTRACTION_WRITER.json")["cases"]}
    r = {c["config"]: c for c in _load("EXTRACTION_REVIEWER.json")["cases"]}
    by_gold = {g["config"]: g for g in amended["cases"]}
    cases = []
    for cfg, q in qs.items():
        if cfg not in w or cfg not in r:
            problems.append(f"{cfg}: no extraction record from the {'writer' if cfg not in w else 'reviewer'}")
            continue
        x, bad = combine(cfg, q, w[cfg], r[cfg])
        problems += bad + consistent(x, by_gold[cfg])
        cases.append(x)
    return amended, {"generated_by": "eval/livecheck_route_v15/amend.py (Amendment 1)", "cases": cases}, problems


def main() -> int:
    amended, extraction, problems = build()
    blocking = [p for p in problems if not p.endswith("(reported)")]
    print("\n".join(problems) if problems else "the agents and the gold agree on every item")
    if problems and not blocking:
        print("(every difference above is recorded and not assessed; none blocks)")
    if blocking:
        print("not written")
        return 1
    (HERE / "GOLD_AMENDED.json").write_text(json.dumps(amended, indent=1) + "\n")
    (HERE / "EXTRACTION_GOLD.json").write_text(json.dumps(extraction, indent=1) + "\n")
    print(f"written: GOLD_AMENDED.json, EXTRACTION_GOLD.json ({len(extraction['cases'])} questions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
