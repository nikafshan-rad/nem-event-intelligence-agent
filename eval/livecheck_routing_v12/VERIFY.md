# Brief: independently verify 24 fresh cases and 18 development golds

Another agent wrote 24 fresh cases following `BRIEF.md` in this kit (`out/cases.json`). Separately, 18 development
questions have expected resolutions in `dev/DEV_GOLD.json` (their questions are in `dev/questions.json`). Check every
case **independently, against the data**. Work **only inside this kit directory**; the rules are at the end.

## What to check

### For each fresh case (Q01–Q24)

1. **The expected outcome is right for the question as written:**
   - **`bound`:** every required field is pinned down by the question's own words, or by its request field:
     - **forecast run:** region, selection rule, and target half-hour (date with year, time, zone, and whether start
       or end);
     - **maximum:** region, measure and window.
   - **`clarify`:** a careful analyst could not tell what is meant. `missing` names what is missing or ambiguous. If an
     analyst could tell, mark the case REVISE.
   - **`no_request`:** it asks for neither a specific run nor a demand maximum.
   - **`as_of_availability`:** it asks what was public or known at a cutoff.
2. **Times and windows,** recomputed by you in UTC:
   - the target half-hour end, the issue time and the as-of cutoff;
   - window bounds: a whole local day as (local midnight, next local midnight]; an event window exactly as in
     `data/events.json`; explicit bounds.

   Apply the brief's conventions: interval end, AEST UTC+10, ACST UTC+9:30, market time UTC+10.
3. **The data:**
   - **`last_issued_before`:** a run issued before the half-hour starts forecasts it. Identify the last such run.
   - **`issued_at`:** the stated time names exactly one run (to the minute: no other run within 10 minutes), and that
     run forecasts the half-hour.
   - **Request cutoff:** the run is public (`available_at_utc`) by the cutoff.
   - **Maxima:** the data holds every interval of the window for that measure. Recompute the maximum's value and
     interval.
4. **Grounding:** `grounding` quotes words that really are in the question (or names the request field), and those
   words establish each field. A keyword alone does not establish a relationship.
5. **The mix, IDs and format,** against the brief's table: counts per kind and outcome, the minimum counts of rules,
   window kinds and measures, IDs Q01–Q24 in order, and `request` used only as allowed.
6. **Variety:** note any near-duplicate pair.

### For each development gold (`dev/DEV_GOLD.json`, 18 cases)

Check that each expected resolution is right for its question (`dev/questions.json`), with the same rules, and
recompute every time and window from the question and the data:
- the outcome;
- the region;
- the run rule, the target half-hour end and any issue time;
- the measure and window;
- the as-of cutoff, from the question's own words or its request field.

## Output

Write `out/VERIFICATION.json`:

```json
{"verified_by": "independent verifier (agent)", "generated_at": "<UTC>",
 "cases_sha256": "<SHA-256 of out/cases.json>", "dev_gold_sha256": "<SHA-256 of dev/DEV_GOLD.json>",
 "result": "PASS|REVISE",
 "fresh": [{"case_id": "Q01", "verdict": "PASS|REVISE", "recomputed": "<your UTC values and data findings>",
            "note": "<why, if REVISE>"}],
 "dev": [{"case_id": "K05", "verdict": "PASS|REVISE", "recomputed": "<...>", "note": "<...>"}]}
```

`result` is PASS only if every case passes. Do not edit `out/cases.json` or anything under `dev/`.

## Independence rules (important)

- Read and run only what is inside this kit directory (`BRIEF.md`, `VERIFY.md`, `DATA.md`, `data/`, `dev/`, `venv/`,
  `out/`). Do **not** open `work/` (the writer's files), `overlap/` or `MANIFEST.json`. You may create `verify/`.
- Do **not** open, list or search anything else on this machine. Do not use the web.
- In your final message, list the files you read and the commands you ran, and each case's ID and verdict, with a short
  reason for any REVISE. Do not quote questions or expected values.
