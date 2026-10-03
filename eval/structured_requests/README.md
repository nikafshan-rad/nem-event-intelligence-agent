# I-18 paraphrase matrix: development test material

This material tests whether forecast-run selection and demand-maximum requests are resolved however they are worded
(I-18, `docs/issue-tracker.md`). It is **development test material, not independent Live evidence**. The
implementation was adjusted after the first recorded run, using that run's failures (below), so later runs are not
held-out results.

## Files, in the order they were committed

| File | What it is | Commit |
|---|---|---|
| `BRIEF.md`, `VERIFY.md`, `build_kit.py` | The writer's and verifier's briefs, and the builder of their kit (no parser pattern, no fix code, no earlier question text) | `1d704d4` |
| `matrix.json` | 60 cases (questions, request fields, expected resolution) by an independent writer, before any implementation | `e9cf6b6` |
| `VERIFICATION.round1.json` | The independent verifier's first check: REVISE, for two notes only (P21, P31) | `4e495d5` |
| `matrix.json` (revised), `VERIFICATION.json` | The writer corrected those two notes only (checked byte for byte); the verifier's recheck: PASS, 60 of 60 | `4e495d5` |
| `FIELDS_BRIEF.md`, `fields.json` | The routing decision a careful model following prompts v12 would return for each case, written by a third independent agent from the routing instructions and schema only (no code) | `d5c7f81` |
| `run_matrix.py` | Runs every case three ways and scores it | `d5c7f81` |
| `RUN1.json` | **The first recorded run** (code `d5c7f81`), before any adjustment | `b772614` |
| `RUN2.json` | The run on this PR's final code | this PR |

**The mix:**
- **forecast run:** 15 bound, 6 clarify, 2 availability as-of, 1 bound with a conflict note;
- **demand maximum:** 16 bound, 7 clarify, 1 bound with a conflict note;
- **no request:** 12.

## How it is run

`python eval/structured_requests/run_matrix.py OUT.json` runs offline: no model call, no key, no ledger entry. Each
case goes through the Live routing path (`live.checked_route`, `service.resolve_routed`) with its routing decision
from `fields.json`, in three ways:
- **(a) absent:** without the `requested` field, as in every route recorded before prompts v12;
- **(b) correct:** as written;
- **(c) adversarial:** with the `requested` field mutated: unquoted words, shifted times, a flipped start or end, a
  swapped measure, window or rule, and requests invented for questions that make none.

**Verdicts.** Containment and supply are counted separately, and a clarification never counts as supplied:
- `SUPPLIED`: bound as expected;
- `CONTAINED`: sent back, although a binding was expected;
- `CLARIFIED`: sent back, as expected;
- `OVER_CLARIFIED`: sent back, although no request was made;
- `WRONG`: a wrong binding;
- `UNBOUND`: proceeded without the expected binding or clarification.

**Pass rules.**
- **(a) and (c):** no case is `WRONG`, `UNBOUND`, `NOTE_MISSING` or `AS_OF_WRONG`.
- **(b):** in addition, every expected binding is `SUPPLIED`.

## Results

| Run | (a) absent | (b) correct fields | (c) adversarial |
|---|---|---|---|
| RUN1 (`d5c7f81`) | FAILS: 13 unbound, 2 wrong; 6 of 33 supplied | FAILS: 22 of 33 supplied, 2 wrong, 1 unbound, 1 note missing | FAILS: 9 wrong, 4 unbound, 1 note missing |
| RUN2 (final) | 1 unbound (P20, a departure, below); 6 of 33 supplied, the rest sent back | passes: 33 of 33 supplied | passes: no wrong binding |

In (c), a request the mutation invents for a question that makes none is still a detection: it is sent back, never
bound (24 over-clarifications).

**What RUN1's failures led to.** These are general rules, none specific to a case:
- **The run cue** reads word proximity instead of fixed phrases ("the last one issued before", "with issue time").
- **The maximum cue** reaches 12 words instead of 8.
- **Dates:**
  - a day and month written without the year take the question's one year;
  - "29/07/2026" is read when only one reading is a date;
  - "13:00 market" is no longer read as a day and a month (a real month name is required).
- **Zones:** "local" and a place's possessive ("Brisbane's") name the region's or the place's zone.
- **"at its maximum"** is the measure's own extreme, not a value at the price peak.
- **A whole local day** must be shown by day wording or a date, with no clock time or event in the quoted words, and
  nothing narrowing the window in the question. "Midnight to midnight" is whole-day wording.
- **Explicit windows:** "through 1 am the next morning" crosses midnight.
- **Two clock times** joined by "and" form a range only after "between". After an end word they are a list
  ("ending 12:30 and 13:00").
- **A model's half-hour** is used only when the model claims an end and its quoted words read to the same end.
- **Conflicts:**
  - a second measure with a peak word attached, whose maximum was not read, sends the question back;
  - a whole day and an event window named together are a conflict;
  - a request window that differs from the question's own window is noted with the answer.
- **An as-of question** that also asks for the run issued before the half-hour gets that run, under the cutoff (as
  K07's frozen gold has it for a request cutoff). Otherwise as-of questions keep the availability selection.

**Departures from the registered criteria.**
- **P20 in (a):** "What was the operational demand forecast for NSW1's half-hour ending 19:00 AEST on 30 July
  2026?" The matrix expects a clarification (no run rule). Without model fields it is not detected: it singles out no
  run. It keeps the documented default (the latest run available before the half-hour, named as such). Sending
  every such question back would change many evaluated forecast questions outside this scope. With the routing
  model's reading (`unclear`), it is sent back.
- **P56 and P59, over-clarified in (a) and (b):** the routing decision itself asks for a region or a date, a
  choice of the field writer. It is not the resolver.
