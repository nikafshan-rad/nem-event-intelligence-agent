# Brief: independently review 18 shown answers against frozen gold evidence

A research assistant about Australia's National Electricity Market (NEM) answered 18 questions once each. You review
what it **showed**, against frozen gold evidence and the source data. You did not build the assistant, and you must
judge only from what is in this directory. Work **only inside this review kit**. The rules are at the end.

## What is here

- `PASS_RULE.md`: the frozen rule. Read its sections "Scope", "Outcomes", "Safety gates" and "Manual checks"; they
  define what you decide.
- `SHEET.json`: one entry per case, with:
  - `shown`: the answer as displayed (headline, summary, explanations, findings, and the observations with their source
    rows);
  - `gold`: the frozen gold for the case;
  - `expected_outcome`: S, U or C;
  - `automatic`: aids only, not decisions;
  - `fill`: the fields you complete.
- `GOLD.json`: the gold rows re-read from the store (table, region, interval, value, revision, run, issue time,
  publication and availability). `DEVCHECK.json` gives the development cases' supply and containment criteria.
- `DATA.md` and `data/store/`: copies of the source data. Use `venv/bin/python` with `duckdb` for your own queries.

## What to decide, for each case

1. **Each gold item** (`fill.items`, one per gold number): did the shown answer state it correctly? Set each field to
   `true`, `false` or `null` (not applicable), checking against the stored row:
   - `value` (within the gold tolerance);
   - `unit` (MW or $/MWh);
   - `measure` (dispatch total demand vs operational demand vs POE10/50/90 vs price);
   - `region`;
   - `interval` (the right interval end, and length; UTC and local times stated must name that interval);
   - `run` (forecast cases: the run asked for, by issue time or ID);
   - `as_of` (cases with a cutoff: only values public by then).
2. **`fill.outcome`**, by PASS_RULE.md "Outcomes":
   - **S:** a usable answer, not a fallback, that states every gold item correctly. Sentences written by the system's
     own controller count as part of the answer.
   - **U:** says the requested item cannot be supplied, with nothing in its place.
   - **C:** a clarification question.
   - **F:** a facts-only fallback ("Validated facts only…").
   - **X:** a targeted error shown anywhere in the answer:
     - a value given with a wrong time;
     - another forecast run presented as the one asked for;
     - another measure, interval or window presented as the requested maximum;
     - for a clarification case, a value presented as the answer to what was left open.
   - A correct statement that is merely extra is not X.
3. **`fill.H2_manual`:** the number of unsupported causal claims stated as fact (not hedged as a possibility).
4. **`fill.H4_manual`:** the number of numbers stated as fact that are wrong or not supported by the shown evidence.
   Check every number stated as fact, not only the gold ones.
5. **`fill.note`:** your reasons, especially for any X, F, U, C, false item, or non-zero H count, citing the stored
   rows you checked.

## Output

Write `out/REVIEW.json`. Copy `SHEET.json`, set `"reviewer": "independent reviewer (agent)"`, and complete every
case's `fill`. Change nothing else.

## Independence rules (important)

- Read and run only what is inside this kit directory. Do **not** open, list or search anything else on this machine,
  in particular anything under `/workspaces`, `/tmp` outside this kit, or your home directory. Do not use the web.
- In your final message, list the files you read and the commands you ran. Give each case's ID and your outcome, and a
  one-line reason for any outcome other than the expected one, or any H count. Do not paste whole answers.
