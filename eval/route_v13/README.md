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
