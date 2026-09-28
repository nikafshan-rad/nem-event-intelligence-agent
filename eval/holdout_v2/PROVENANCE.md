# Held-out set v2: provenance

- **File:** `eval/holdout_v2/cases.json` (14 cases), SHA-256
  `413f875b4760855c8970c2bf5790e7633f53e0d21f090d699cabcffa46c99ebf`. Frozen before any Live run on it.
- **Writer:** a fresh subagent with no conversation history. It was given only a kit directory outside the repository
  containing:
  - `BRIEF.md` (copied here): the system's documented scope, its tools per intent, the case schema and the
    gold-evidence rules;
  - `DATA.md` (copied here): a data dictionary generated from the files;
  - copies of the pinned data store and the document corpus;
  - the list of 8 verified events and the analysis threshold;
  - its own Python environment.
- **What the kit did not contain:** this repository's failure analysis (`docs/live-gates.md`), prompts, README,
  source code, any Live output or trace, and the existing 40 evaluation questions. The writer was told not to access
  anything outside the kit and listed every file it read and command it ran:
  - all were inside the kit;
  - one oversized command output was auto-saved by the tool harness to the session's tool-results folder, and the
    writer did not open it.
- **Independent gold check:** a second fresh subagent, with the same kit-only rules, re-derived every gold value with
  its own queries (not the writer's SQL):
  - checked every snippet verbatim against its passage;
  - checked the as-of rows were the latest public ones at each cutoff;
  - checked each case's expected fields against the brief.

  Result: **14/14 PASS**. Its access log is also kit-only (plus one harness auto-save it did not open).
- **Blind compatibility check** by the developer, which prints counts and case IDs only: 14 cases in the required
  mix; 16 gold numbers and 6 gold citations all resolve in the repository's own store and index; no problems.
- **The developer did not read the questions, labels or gold values** before the frozen run.
- Cases the writer flagged as uncertain, for the human reviewer:
  - H02: a gold price row is marked non-firm;
  - H08, H09: another document may answer equally well;
  - H10: could plausibly be routed as an event review;
  - H12: `group` holds only the first region;
  - H13: names an asset from a notice;
  - H14: extra `must_not_contain` entries.
