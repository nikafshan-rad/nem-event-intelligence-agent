# Amendment 1: the scorer's open definitions, fixed before any run

Written on 2026-10-05 at the owner's instruction, before any paid call and before any Live result exists.

It amends `PROTOCOL.md`, pre-registered in `3252ff5`. Two files are kept unchanged as the original record:
- `PROTOCOL.md`;
- the first freeze, `FREEZE_1.json` (committed as `FREEZE.json` in `6c06348`).

Where they differ from this amendment, the amendment governs. `FREEZE.json` is the re-freeze under it.

**This file authorises no paid call.**

## Why
The first freeze's scorer settled three points the protocol left open. Its documentation recorded them, but the
protocol did not. Its reading of the not-answered parts could also drop "other" when a note names it beside weather or
price. The owner asked for the gap to be closed and the definitions recorded in the protocol before any run, without
changing questions or gold to fit the application.

## Unchanged
- **Questions, request fields and gold:** `GOLD.json` and `cases.json` are byte-identical, and so are the writer's,
  reviewer's and reconciliation records.
- **The sample:** 69 configurations and 322 slots; the repeats; the order, slot for slot.
- **Money and denominators:** the reservations, the run cap (USD 1.803166) and the denominators (31 answerable held-out
  questions; 93 availability slots per arm).
- **The code and settings:**
  - `src/` is `76c4341`'s tree;
  - prompts v16 and v17, the model, the 2,000-token routing cap, and the arms (A: v15; B: v16 with V1);
  - the runner, `run_route.py` and `run_eval.py`, byte-identical.
- **The acceptance criteria, thresholds and verdict order**, with their denominators and interval.
- **No application code, wording, rule, prompt or default changes.**

## 1. Not-answered kinds are read from structured metadata
**What a resolution names as not answered.** The scorer takes, for both arms alike, the kinds each not-answered note
was built from. It captures them from the application's own note function (`structured.not_answered_note`) during an
offline re-resolution of the recorded decision.
- The re-resolution uses the same frozen code, data and policy.
- It counts only when it reproduces the recorded resolution and offered tools exactly.
- The function's text and behaviour are unchanged: it is wrapped only to read its input. The wrapper exists only in
  the scorer, and the paid run's path is untouched.

**Where re-resolution cannot reproduce a record**, the scorer uses the record's own structured field (a bound
forecast's `unsupported` kinds) with the note text, and flags the slot. The text names `other` only when it is the sole
kind, which is the gap this closes. Each arm's report counts the slots by source.

**Every gold-asked unsupported part must be accounted for.** A gold-asked unsupported part is a weather, price or other
forecast that the gold marks `asked`. In a resolution that proceeds:
- **resolved** is exact only if the named kinds equal the gold's not-answered kinds;
- **`event_review_without_demand_forecast`** is acceptable only if:
  - every gold-asked unsupported part is named;
  - a gold-asked forecast of an unshown kind is covered, either by the note that a forecast is mentioned without
    showing which or by a not-answered note;
  - no kind is named that the gold does not ask for.

**Declined and background parts** are never required. Naming one as not answered is a mismatch, unless an asked
forecast of an unshown kind could be the one named.

**A gold consistency check** (`gold.py check`) now requires each resolution's not-answered kinds to be exactly its
asked unsupported parts. The frozen gold already meets it, and nothing in it changed.

## 2. A prohibited binding retained in a sent-back record
**Definition:** a resolution that does not proceed (sent back or refused) whose requests still hold a bound forecast
request, forecast run or demand maximum. It applies to slots with a reading only. A slot with no reading is scored as
no reading.

**How it is scored:**
- **Its evidence words overlap a declined or background anchor:** C4, labelled "retained in a sent-back record". It is
  a critical violation and counts toward the B gate. The C4 definition carries no "proceeds" condition, and the
  binding would govern the request once the stated blocker were resolved. Each arm's report counts it separately.
- **It binds a request that C3 would prohibit in a resolution that proceeds:** a retained mis-binding (a request
  other than the gold's, or bound where the gold resolves none). It is reported for each arm and is not a critical
  violation, because C3 is defined for resolutions that proceed and nothing is answered.
- **A control holding any binding** is not "sent back safely" for criterion 4, as before.

**Tool eligibility and execution are scored apart, never inferred from a binding:**
- **C1:** the demand-forecast tools Live would offer. A resolution that does not proceed offers none.
- **C6:** tools executed and case-note writes, from the slot's own counts.

## 3. Partial handling stays outside exact resolution
**Partial handling:** a question whose gold asks two or more distinct supported requests, in a resolution that
proceeds, with at least one bound and every other one named as not given (section 4).

**How it is scored:**
- It is reported for both arms.
- It is never acceptable, and never an exact resolution, even where a gold record resolves one of the requests.
- It is not also a silent omission.
- Its one binding is not also counted as a C3 "bound where the gold resolves none". Region and cutoff are still
  checked.

## 4. Silent omission, defined against the gold
In a resolution that proceeds, each gold-asked supported request (a demand forecast or a demand maximum) must be
accounted for in one of these ways:
- **bound:** a bound forecast request for a demand forecast, or a bound maximum for a demand maximum. Bound fields that
  differ from the gold's are C3.
- **served** (a demand forecast only): the resolution proceeds as an investigation the gold accepts for the question,
  its intent in the gold's intents, and offers the demand-forecast tools the gold makes eligible. It is reported as
  "served, not bound" and is never exact, since exact resolution needs the request bound as the gold resolves it.
  - In the frozen gold, every resolved forecast record accepts `forecast_review` only, so this applies to no frozen
    question.
- **named as not given** (a demand forecast only): by the note that a forecast is mentioned without showing which,
  which states that no operational demand forecast is compared or given for it.
  - A note naming another kind of forecast (weather, price, other) does not name a demand request.
  - No note names a demand maximum.

A gold-asked supported request accounted for in none of these ways is a silent omission. Bound requests are matched by
kind: one forecast and one maximum. This replaces the first freeze's rule, under which any not-answered note named an
unbound demand forecast, and under which an event review's unbound forecast was judged by what the resolvers do rather
than by the gold.

## 5. The repository-wide maximum-question scan (no protocol change)
`tests/provider/test_requested_maximum.py` scans every question in `eval/` and `artifacts/live/` for maximum requests.
It now excludes this evaluation by its exact directory names only: `compare_route_v15_v16`, `CMP-route-v15-v16` and
`CMP-route-v15-v16-run`.
- **What is excluded:** a test checks that the excluded files are only this evaluation's, and that every question they
  hold is one of its own.
- **What is unchanged:** the scan's other exclusions, its assertion, and every application test in the file.

## Files
**Changed:**
- `score.py`;
- `gold.py` (the consistency check only);
- `freeze.py` (it records this amendment and the freeze it supersedes);
- `tests/eval/test_compare_route_v15_v16.py`;
- `tests/provider/test_requested_maximum.py` (exact names);
- `PROVENANCE.md` (history appended).

**Added:**
- this file;
- `FREEZE_1.json` (the first freeze, byte-identical).

**Re-frozen:** `FREEZE.json`.
