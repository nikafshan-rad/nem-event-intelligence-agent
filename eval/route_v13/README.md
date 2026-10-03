# Route contract v13: offline acceptance records (D26)

These records support the acceptance criteria of D26 in `docs/decisions.md`. They are offline: no model call, no key,
and a scratch ledger only. They are development checks, not Live evidence. Any reduction in routing truncation stays
a hypothesis until a separately approved Live verification.

| File | What it is |
| --- | --- |
| `resolve_saved_routes.py` | Resolves every saved Live routing decision (`artifacts/live/*/`, 218 of them) with the code on `sys.path`, as the Live path does |
| `compare.py` | Compares the v12 and v13 resolutions (saved decisions and the I-18 paraphrase matrix), and checks every changed binding against independently checked gold |
| `HISTORICAL_BINDINGS.json` | Every changed binding: its v12 and v13 resolution, its gold, and the check |
| `MATRIX_COMPARISON.json` | Both matrix summaries, and every changed verdict |
| `time_conversion.py`, `TIME_CONVERSION.json` | Code's conversion of the quoted words against each v12 model timestamp and the gold. Model timestamps are not ground truth |

**How they were made:**
1. A worktree of `main` at `5dfeaec` gave the v12 code:
   `PYTHONPATH=<worktree>/src python eval/route_v13/resolve_saved_routes.py ROUTES_V12.json`, and the same for
   `eval/structured_requests/run_matrix.py`.
2. This branch gave the v13 outputs with the same two commands.
3. Then `python eval/route_v13/compare.py ROUTES_V12.json ROUTES_V13.json MATRIX_V12.json MATRIX_V13.json` and
   `python eval/route_v13/time_conversion.py TIME_CONVERSION.json`.

## Historical v12 scoring is reproducible
The v12 matrix scoring is reproduced exactly from the v12 code in git history. Running
`run_matrix.py` from a worktree of `main` at `5dfeaec` (with `PYTHONPATH` on that worktree's `src/`) reproduces the
committed `eval/structured_requests/RUN2.json`: the same matrix and fields hashes, the same summary, and the same
verdict and detail for all 350 rows. The v12 summary is also kept in `MATRIX_COMPARISON.json`.

## The 43 changed paraphrase-matrix verdicts (`MATRIX_COMPARISON.json`, `categories`)

| Mode | v12 → v13 | Rows | Cases | Why |
| --- | --- | --- | --- | --- |
| c_time_plus_30 | CONTAINED → SUPPLIED | 22 | P01–P14, P23, P24, P35–P38, P46, P47 | The mutation shifts the v12 model timestamps, which v13 does not read. The binding is code's reading of the quoted words, which the scorer confirms is the gold binding |
| c_start_end_flipped | CONTAINED → SUPPLIED | 16 | P01–P14, P23, P24 | The same: the flipped timestamp is not read |
| a_absent, b_correct, c_rule_swapped, c_start_end_flipped, c_time_plus_30 | AS_OF_OK → CONTAINED | 5 | P22 | The v12 cutoff timestamp is detection only. P22's wording ("Put yourself at 16:30 Adelaide time") has no as-of words the parser reads, and v12 quoted none, so the question is sent back, never left without its cutoff. Quoted under v13, the words are applied as the cutoff, as tested for Q23 |

Modes b and c still pass, with 33 of 33 supplied in b. Mode a still fails only on P20, as under v12.

## Saved routing decisions: 6 of 218 changed (`HISTORICAL_BINDINGS.json`)

| Case | v12 → v13 | Against gold |
| --- | --- | --- |
| D01, F06 (`LC-maxima-run`) | sent back → bound | Match |
| K10 (`LC-route-v12-e2e`) | sent back → bound | Matches `eval/livecheck_i15_17` |
| Q11 (`LC-route-v12-fresh`) | sent back → bound | Matches `eval/livecheck_routing_v12` |
| Q13 (`LC-route-v12-fresh`) | bound → sent back | Its gold is a binding. The v12 reading quoted only "that event's window", so the event's identifying time (02:35) is held by no role's words. This is the cost of the guarantee below; a v13 reading that quotes the identifying words binds the gold window, as tested |
| Q23 (`LC-route-v12-fresh`) | sent back → sent back | Unchanged outcome (several dates); its v12 cutoff timestamp is now detection only |

## F07 end to end (`f07_end_to_end.py`, `F07_END_TO_END.json`)
F07 runs through the fake transport, with no network and a scratch ledger.

**The input:**
- **the question;**
- **the request override:** the case's `as_of_utc` field;
- **a SYNTHETIC v13 routing reading:** written by the developer, and not Live evidence.

**The resolution:**
- **measure:** the question parser;
- **window:** the reading's located words "that entire local day", with the question's own date, built by code in
  Australia/Brisbane;
- **cutoff:** the request override. Code cannot convert the question's cutoff words, because "noon" is unsupported.
  They are located, so they hold "noon", which then does not narrow the window. They are noted as not comparable,
  and never applied.

**Against independent gold:** the window, the cutoff, the measure and the computed result (not established; highest
held 5693 MW; 8 of 48 held; 40 excluded) all match `eval/livecheck_maxima/GOLD.json`.

**Contrasts:**
- **without the request field:** sent back with the cutoff clarification after the routing call alone, with no tool
  run;
- **without the cutoff's quoted words:** "noon" narrows the window, and the question is sent back.
