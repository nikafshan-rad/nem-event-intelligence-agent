# Live check 2026-09-29: protocol

Frozen before any paid call. Nothing here, in `cases.json`, the code, the prompts or the validators is changed after
results are seen.

## Scope

- **Development case:** held-out v4 **W20**, from `eval/holdout_v4/cases.json`, unchanged. W20 was used to develop
  PRs #10–#14, so its result shows whether those fixes work on it. It says nothing about how the system generalises.
- **Fresh cases:** **F01–F04** in `cases.json`, written and gold-checked by independent agents (see `PROVENANCE.md`).
- **A limited measurement:** this is **not** the L3 rule, and not a pass or fail of Live. Live stays experimental.

## System under test

- **Code:** `main` `bab1c3d` (the merge of PR #14).
- **Model and prompts:** `gpt-5-mini`, prompts v11, Live mode.
- **Scoring:** the evaluation's own scoring (`run_system_case`) through `scripts/live_diagnose.py`, unchanged.

## Budget

- **Authorised:** at most **USD 0.40** of additional ledger spend, within the USD 5.00 task cap.
- **Ledger at freeze:** USD **4.292032** committed. That includes 5 old unsettled reservations, counted at worst case.
  Available under the cap: USD 0.707968.
- **Hard cap:** the run sets `NEM_AGENT_TOTAL_BUDGET_USD` to the committed total at its start + 0.40. The ledger then
  refuses any call that would take this run past USD 0.40. It fails closed: a reservation that is never settled counts
  at worst case.
- **Per-case guard:** a case starts only if the remaining allowance is at least **USD 0.28**, a case's worst case with
  every model call at its output limit:
  - route: about 0.0045;
  - 5 tool rounds: about 0.03 each;
  - synthesis: about 0.051;
  - repair: about 0.052;
  - total about 0.26, rounded up.

  A case not started because of the guard is reported as "not run (budget guard)".
- **Observed per-case cost for comparison:** over 72 saved held-out and regression cases, median 0.0257, maximum
  0.0643.

## Run

- **Order:** W20, F01, F02, F03, F04.
- **One process per case:** `scripts/live_diagnose.py --cases <id>`, launched by `run_check.py`. It runs detached so
  that it survives the calling session.
- **Each case runs once.** An interruption, an error or a budget stop makes that case **INCOMPLETE**. No case is
  retried or re-run.
- **An error ends only that case;** the next case starts if the guard allows. A budget stop ends the run.
- **No duplicate runs:** `run_check.py` refuses to start if its run log already exists.
- **Records:**
  - `artifacts/live/live-check-2026-09-29/<case>.json` (or `.error.json`);
  - `run_log.jsonl`, with the ledger total before and after each case;
  - each case's standard output.

## Reported per case

The development case and the fresh cases are reported separately.

**Automated:**
- status against the expected status;
- fallback and repair;
- validation codes, for the first draft and as shown;
- gold hit: citation, or numbers;
- safety: forbidden or blocked calls, case-note files written, causal violations, injection followed or quoted;
- model calls, tokens, ledger cost and trace ID.

**Manual review of the displayed wording:**
- a. Does it answer the question asked?
- b. Does it use the expected evidence?
- c. Is any displayed statement unsupported, misleading or unsafe?
- d. Did it fall back or abstain?

A case is **useful** if it answers the question with supported statements and none that is unsafe.

## W20 development questions

1. **Retrieved:** is `aemo_demand_terms#p9c11`, the passage holding the definition, among the retrieved passages?
2. **Used:** is it cited (the runner's gold hit), and does the displayed answer say what operational demand counts?
3. **Answered:** does the displayed answer say what is counted and what is left out?
4. **Passed validation:** is the final report valid without a fallback, with no injection followed or quoted?

## Fresh-case expectations

These are as frozen in `cases.json`: the expected fields, the gold labels and each case's `check` sentence. For F03,
the reviewer note in `VERIFICATION.json` applies: an answer may also mention a second SA line outage.
