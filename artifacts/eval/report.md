# Offline evaluation report (replay)

Generated 2026-09-28T09:37:16Z · code `431b9d6-dirty` · data `8c14c217f5570d32` · corpus `221b6ea0f21e006d` · controller `scripted-replay-controller/1` · cases {'dev': 19, 'test': 21}.

Replay uses a scripted, rule-based controller and router (no LLM). These numbers measure the tools, retrieval, validators and templates, **not** a hosted model. Hosted-model results are UNVERIFIED (no API key).

| Metric | System (held-out test) | Baseline: table (test) | Baseline: retrieval-only (test) | System (dev) |
| --- | --- | --- | --- | --- |
| Status matches expectation | 20/21 (95%) | 15/20 (75%) | 18/20 (90%) | 19/19 (100%) |
| Answerable cases answered | 17/18 (94%) | 15/18 (83%) | 18/18 (100%) | 15/15 (100%) |
| Unanswerable cases safely handled | 2/2 (100%) | 0/2 (0%) | 0/2 (0%) | 3/3 (100%) |
| Required-tool recall (answerable) | 43/43 (100%) | 0/0 | 0/0 | 44/44 (100%) |
| Numeric traceability (accepted) | 96/96 (100%) | 881/881 (100%) | 0/0 | 90/90 (100%) |
| Citation validity (accepted) | 51/51 (100%) | 0/0 | 100/100 (100%) | 47/47 (100%) |
| Gold numbers found | 13/13 (100%) | 13/13 (100%) | 0/13 (0%) | 15/15 (100%) |
| Forecast gold (MAE, pairs, as-of run) | 5/5 (100%) | 3/5 (60%) | 0/5 (0%) | 5/5 (100%) |
| Gold citation found (document cases) | 3/4 (75%) | 0/1 (0%) | 2/4 (50%) | 4/4 (100%) |
| As-of leakage (count) | 0 | 1167 | 7 | 0 |
| Causal-claim violations | 0 | 0 | 0 | 0 |
| Wrong-region findings | 0 | 0 | 0 | 0 |
| Injection followed | 0 | 0 | 0 | 0 |
| Unauthorized writes | 0 | 0 | 0 | 0 |
| Blocked tool calls | 0 | 0 | 0 | 0 |
| Latency p50 / p95 (ms) | 197.2 / 358.5 | 39.6 / 119.3 | 0.7 / 0.9 | 251.8 / 438.3 |

Routing (scripted router, test): macro-F1 0.9222 over 20 investigation cases (19 correct).

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

- DOC04 (test): status `needs_clarification`, expected False; codes []; Clarification needed: Which NEM region (NSW1, QLD1, SA1, TAS1 or VIC1)? Which date (or UTC window) should be investigated?
- gold miss DOC04 (test): numbers None/None, forecast None, citation False

## Limitations

- 40 cases over 8 events in 4 regions within one fortnight: small, and not a measure of general accuracy.
- The system and the gold labels share the ingested data; gold is computed by independent SQL, not by the tools.
- Interpretive quality (hypothesis soundness) is flagged `human_review_needed` and is not auto-scored.
- The retrieval-only baseline is a deterministic stand-in for an LLM document chatbot.
