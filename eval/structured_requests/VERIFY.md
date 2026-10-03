# Brief: independently verify a paraphrase matrix of 60 request-resolution cases

Another agent wrote 60 cases following `BRIEF.md` in this kit. Check every case **independently**. Work **only
inside this kit directory**; the rules are at the end.

## What to check, for each case

1. **The expected outcome is right for the question as written:**
   - **`bound`:** every required field is pinned down by the question's own words, or by its request fields:
     - **forecast run:** region, selection rule, and target half-hour (date with year, time, zone, and whether start
       or end);
     - **maximum:** region, measure and window.
   - **`clarify`:** a careful analyst could not tell what is meant. `missing` names what is missing or ambiguous. If an
     analyst could tell, mark the case REVISE.
   - **`as_of_availability`:** the question asks what was public or known at a cutoff.
   - **`no_request`:** the question asks for neither a specific run nor a demand maximum (for example, demand at the
     price peak).
   - **`bound_with_conflict_note`:** a request field and the question's wording genuinely conflict. The request field
     is the one used.
2. **Times and windows,** recomputed by you in UTC:
   - the target half-hour end;
   - the issue time;
   - the window bounds: whole local day; an event window exactly as in `data/events.json`; explicit bounds.

   Apply the brief's conventions: interval end, AEST UTC+10, ACST UTC+9:30, market time UTC+10.
3. **Grounding:** `grounding` quotes words that really are in the question (or names the request field), and those
   words establish the field. A keyword alone does not establish a relationship.
4. **The mix, IDs and format,** against the brief: the counts per path and outcome, IDs P01–P60 in order, and
   `request` used only as the brief allows.
5. **Variety:** the bound cases use varied wording, as the brief requires. Note any near-duplicate.

## Output

Write `out/VERIFICATION.json`:

```json
{"verified_by": "independent verifier (agent)", "generated_at": "<UTC>", "file_sha256": "<SHA-256 of out/matrix.json>",
 "result": "PASS|REVISE", "cases": [{"id": "P01", "verdict": "PASS|REVISE", "recomputed": "<your UTC values>",
 "note": "<why, if REVISE>"}]}
```

`result` is PASS only if every case passes. Do not edit `out/matrix.json`.

## Independence rules (important)

- Read and run only what is inside this kit directory (`BRIEF.md`, `VERIFY.md`, `DATA.md`, `data/`, `venv/`, `out/`).
  Do **not** open `work/` (the writer's files), `overlap/` or `MANIFEST.json`. You may create `verify/`.
- Do **not** open, list or search anything else on this machine. Do not use the web.
- In your final message, list the files you read and the commands you ran, and each case's ID and verdict, with a
  short reason for any REVISE. Do not quote questions or expected values.
