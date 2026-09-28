Write the investigation report as JSON matching the schema. Use only evidence returned by the tools above.
An independent validator checks every rule below; a report that breaks one is replaced by bare tool values.

Numbers
- State a number only if a tool returned it with its own `evidence_id` (e.g. `"value": 4981.0, "evidence_id":
  "ev0433"`). Numbers without their own id (counts, coordinates, heights in variable names such as WS50M, list
  sizes) are context: do not restate them. Refer to a weather variable by its name (e.g. "WS50M wind speed").
- `numeric_claims`: one entry for every number in headline, summary or possible_explanations. `value` is the number
  exactly as displayed in your text, `unit` is the unit the tool gave for that evidence item, `evidence_id` is the
  id holding that value, and `rounding` is the tolerance you applied. A chunk_id or citation_id is never an
  evidence_id.
- Write clock times as HH:MM and dates as YYYY-MM-DD; they are not numeric claims.
- State numbers only for the investigated region.
- Forecast reviews: compare the context's `forecast_targets_utc` with compare_forecast_actual, and set
  `forecast_mae_evidence_id` to the evidence_id of the MAE you report (null for other questions).

Times
- Copy every clock time from a tool output or the context, with its zone: prefer a `*_local` field (e.g.
  "2026-07-31 02:05 ACST", from `event_peak_interval_end_local` or `interval_end_local`); timestamps ending in Z are
  UTC (write "16:35 UTC"). Never convert, shift or re-label a time yourself: the validator rejects any time that no
  tool returned.
- AEMO notices state times as "HHMM hrs" in NEM market time (UTC+10). Use each notice's `clock_times` (UTC and
  local equivalents) and compare times only on the same basis; never call two times coincident unless their UTC
  values show it.

Documents
- `citations`: chunk_id of a retrieved passage, a short quote (one sentence or clause, <= 200 characters) copied
  character-for-character from that passage, including capitalisation and spacing, and what it supports. Documents
  are cited by citation_id; they have no evidence ids.
- Definition and document answers: every summary sentence ends with the [citation_id] of the passage it relies on,
  and either quotes that passage or restates it closely in its own words. Do not add anything the passage does not
  say. If no retrieved passage answers the question, say so and abstain.
- `published_findings`: for a retrieved AEMO market notice for the same region and window, give the citation_id of
  your citation that quotes it. The controller renders the finding as that verbatim quote.
- Elsewhere, refer to a document by its citation id and keep its numbers, identifiers, dates and wording
  (including phrases such as "cause of") inside the quote. Write "AEMO reported a City West transformer trip
  [c1]", not "at 1140 hrs on 30/07/2026 transformer T_1 and breaker 6675 tripped".

What a market-event review covers (the same content as the replay controller's report)
- The price extreme: its value and the local time of its interval end.
- How many 5-minute intervals met the analysis threshold, and the threshold.
- Actual operational demand (get_actual_demand) in the half-hour containing the price extreme (the context's
  `peak_half_hour_end_utc`), and the window's maximum operational demand. Dispatch TOTALDEMAND is a different
  measure: label it as such if you use it.
- AEMO market notices for the region and window, as published_findings; hedged explanations, each with a test.

Explanations and status
- `observation_evidence_ids`: evidence_ids of the key tool observations (the controller copies values and sources).
- `possible_explanations`: hedged hypotheses only ("may", "might", "could"), each with what would test it.
  `supporting_evidence_ids` lists only evidence_ids from tool results (it may be empty); mention related documents
  by citation id in the statement.
- Outside `possible_explanations`, do not use causal wording (caused, due to, because of, led to, resulted in,
  drove, triggered, responsible for).
- `missing_evidence`: data or documents a fuller answer would need; not remarks about tools or ids.
- `status`: "answered" when required tools succeeded and the answer is evidence-backed; "answered_with_caveats" when
  some evidence is missing; "abstained" when the evidence cannot answer the question.
