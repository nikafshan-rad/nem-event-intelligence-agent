# Offline evaluation report (replay)

Generated 2026-10-05T12:31:26Z · code `86f6573` · data `8c14c217f5570d32` · corpus `221b6ea0f21e006d` · controller `scripted-replay-controller/1` · cases {'dev': 19, 'test': 21}.

Replay uses a scripted, rule-based controller and router (no LLM). These numbers measure the tools, retrieval, validators and templates, **not** a hosted model. Hosted-model results are UNVERIFIED (no API key).

| Metric | System (held-out test) | Baseline: table (test) | Baseline: retrieval-only (test) | System (dev) |
| --- | --- | --- | --- | --- |
| Status matches expectation | 18/21 (86%) | 15/20 (75%) | 18/20 (90%) | 19/19 (100%) |
| Answerable cases answered | 15/18 (83%) | 15/18 (83%) | 18/18 (100%) | 15/15 (100%) |
| Unanswerable cases safely handled | 2/2 (100%) | 0/2 (0%) | 0/2 (0%) | 3/3 (100%) |
| Required-tool recall (answerable) | 39/39 (100%) | 0/0 | 0/0 | 44/44 (100%) |
| Numeric traceability (accepted) | 95/95 (100%) | 881/881 (100%) | 0/0 | 100/100 (100%) |
| Citation validity (accepted) | 53/53 (100%) | 0/0 | 100/100 (100%) | 47/47 (100%) |
| Gold numbers found | 13/13 (100%) | 13/13 (100%) | 0/13 (0%) | 15/15 (100%) |
| Forecast gold (MAE, pairs, as-of run) | 1/5 (20%) | 3/5 (60%) | 0/5 (0%) | 0/5 (0%) |
| Gold citation found (document cases) | 3/4 (75%) | 0/1 (0%) | 2/4 (50%) | 4/4 (100%) |
| As-of leakage (count) | 0 | 2130 | 7 | 0 |
| Causal-claim violations | 0 | 0 | 0 | 0 |
| Wrong-region findings | 0 | 0 | 0 | 0 |
| Injection followed | 0 | 0 | 0 | 0 |
| Unauthorized writes | 0 | 0 | 0 | 0 |
| Blocked tool calls | 0 | 0 | 0 | 0 |
| Latency p50 / p95 (ms) | 159.9 / 604.0 | 50.1 / 137.0 | 0.8 / 1.8 | 281.7 / 1010.0 |

Routing (scripted router, test): macro-F1 0.8234 over 20 investigation cases (17 correct).

## Gate checks

- PASS — exactly_40_cases
- PASS — category_counts
- PASS — no_group_in_both_splits
- PASS — provenance_present
- PASS — held_out_ran_end_to_end
- PASS — required_tools_100pct_on_answerable
- PASS — numeric_traceability_100pct_on_accepted
- PASS — citation_ids_resolvable_100pct_on_accepted
- PASS — zero_as_of_leakage
- PASS — zero_unauthorized_writes
- PASS — unanswerable_all_safely_handled
- PASS — not_abstaining_on_everything
- PASS — held_out_metrics_computed

## Baselines

- **baseline_table**: deterministic chart/table from tools; no LLM, retrieval, validation or as-of rules
- **baseline_retrieval_only**: deterministic retrieval-only analogue of a naive document chatbot (unfiltered hybrid search, top-5 passages); NOT an LLM
- **llm_document_chatbot**: UNVERIFIED: requires OPENAI_API_KEY

## Failures and misses (system, all splits)

- FC02 (test): status `needs_clarification`, expected False; codes []; Clarification needed: Which forecast is the question about? This assistant reviews AEMO's operational demand forecasts, and the question does not show that it a
- DOC04 (test): status `needs_clarification`, expected False; codes []; Clarification needed: Which NEM region (NSW1, QLD1, SA1, TAS1 or VIC1)? Which date (or UTC window) should be investigated?
- AMB06 (test): status `needs_clarification`, expected False; codes []; Clarification needed: The question asks about AEMO's operational demand forecasts and also about a forecast of another kind (for example weather or prices). Thi
- gold miss FC01 (test): numbers None/None, forecast {'mae_ok': False, 'n_pairs_ok': False, 'peak_run_ok': True}, citation None
- gold miss FC02 (test): numbers None/None, forecast {'mae_ok': False, 'n_pairs_ok': False, 'peak_run_ok': False}, citation None
- gold miss FC03 (dev): numbers None/None, forecast {'mae_ok': False, 'n_pairs_ok': False, 'peak_run_ok': True}, citation None
- gold miss FC04 (dev): numbers None/None, forecast {'mae_ok': False, 'n_pairs_ok': False, 'peak_run_ok': True}, citation None
- gold miss FC05 (dev): numbers None/None, forecast {'mae_ok': False, 'n_pairs_ok': False, 'peak_run_ok': True}, citation None
- gold miss FC06 (dev): numbers None/None, forecast {'mae_ok': False, 'n_pairs_ok': False, 'peak_run_ok': True}, citation None
- gold miss FC07 (test): numbers None/None, forecast {'mae_ok': False, 'n_pairs_ok': False, 'peak_run_ok': True}, citation None
- gold miss FC09 (dev): numbers None/None, forecast {'mae_ok': False, 'n_pairs_ok': False, 'peak_run_ok': True}, citation None
- gold miss FC10 (test): numbers None/None, forecast {'mae_ok': False, 'n_pairs_ok': False, 'peak_run_ok': True}, citation None
- gold miss DOC04 (test): numbers None/None, forecast None, citation False

## Limitations

- 40 cases over 8 events in 4 regions within one fortnight: small, and not a measure of general accuracy.
- The system and the gold labels share the ingested data; gold is computed by independent SQL, not by the tools.
- Interpretive quality (hypothesis soundness) is flagged `human_review_needed` and is not auto-scored.
- The retrieval-only baseline is a deterministic stand-in for an LLM document chatbot.
