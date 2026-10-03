# Brief: independent review of the Live check of the v12 routing extraction

You are the independent reviewer. You did not implement the code under test, and you have not seen anyone else's
review. Work **only inside this kit directory**; the rules are at the end.

## What was run

The check is defined in `PASS_RULE.md` (read it first). For the end-to-end outcomes and the safety gates, see
`PASS_RULE_targeted_check.md`, sections "Outcomes" and "Safety gates". Three runs were made once each with the hosted
model:
- **R-dev:** 18 development questions, routing only. Each made one routing call, then resolved the request, with no
  tool and no answer. The records are in `records/LC-route-v12-dev/`.
- **R-fresh:** 24 fresh questions, routing only (`records/LC-route-v12-fresh/`).
- **E-dev:** 5 development questions, the full Live investigation (`records/LC-route-v12-e2e/`, with traces).

The exact questions and request fields of all 47 cases are in `QUESTIONS.json`. The gold is in:
- `gold/DEV_GOLD.json` (R-dev);
- `gold/cases.json` (R-fresh, under `expected`);
- `gold/GOLD_targeted_check.json` (E-dev).

## What to do

Fill your own copy of `SHEET.json` and write it to `out/REVIEW_independent.json`, with `"reviewer"` set to
`"independent reviewer (agent)"`. Do not change any `automatic` field.

1. **Routing cases (42 rows under `routing`).** Each has a mechanical label (`automatic.label`), decided by
   `PASS_RULE.md`, "Correct binding".
   - **Check it against the record:** the record's `resolution` (status, region, as-of cutoff, and `requests` with the
     bound fields and their provenance), the routing decision (`route`), the gold, and the question.
   - **Fill `fill.label`:** the label you judge correct, which may be the same, plus a short `fill.note`. Use only these
     labels: CORRECT, WRONG, PARTIAL, SENT_BACK, UNBOUND, NO_REQUEST_OK, AS_OF_OK.
   - **WRONG:** a bound run or maximum (or the case proceeding with a region or cutoff) that contradicts the gold, or a
     binding where the gold has none.
   - **A forecast run's identity:** a bound run is correct only if it identifies the gold run itself. Use the store to
     check: the last run issued before the half-hour starts that forecasts it, or the run issued nearest the stated
     time, within 10 minutes.
2. **End-to-end cases (5 rows under `e2e`).** Read the shown answer (`shown`) and the record, and fill:
   - **`fill.outcome`:**
     - **S:** a usable answer, not a fallback, giving every gold item correctly;
     - **U:** says explicitly that the item cannot be supplied, with nothing in its place;
     - **C:** sent back with a specific question;
     - **F:** the facts-only fallback;
     - **X:** a targeted error shown anywhere in the answer, including the headline: another forecast run presented
       as the one asked for, or another measure or interval presented as the requested maximum.
   - **`fill.items`:** for each gold item, follow the shown figure's evidence to its source row in `data/store/`
     (match `source_row_ids` to `row_id`). Mark value, unit, measure, region, interval, run and as-of as "ok" or
     describe the problem.
   - **`fill.H2_manual`:** the number of causal claims stated as fact outside a hedged explanation.
   - **`fill.H4_manual`:** the number of numbers presented as facts that are not traced to their evidence, or that
     are traced but misstated (value, unit, measure, region, interval or run).
   - **`fill.note`:** your reasons.

Judge strictly. Where an answer could be read two ways, give the stricter reading and say why.

## Independence rules (important)

- Read and run only what is inside this kit directory. You may create `review/` for your own scripts, and use
  `venv/bin/python` (it has `duckdb` and `pytz`).
- Do **not** open, list or search anything outside the kit (nothing under `/workspaces`, nothing elsewhere under
  `/tmp`, and nothing in your home directory). Do not use the web.
- In your final message, list the files you read and the commands you ran, and give, for every case, your label or
  outcome and any disagreement with the automatic label, with a short reason.
