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

Times
- Every clock time you write carries its time zone, copied from the tool output: prefer the region-local form
  (e.g. "2026-07-31 02:05 ACST"); tool timestamps ending in Z are UTC (write "16:35 UTC").
- AEMO notices state times as "HHMM hrs" in NEM market time (UTC+10). Use each notice's `clock_times` (UTC and
  local equivalents) and compare times only on the same basis; never call two times coincident unless their UTC
  values show it.

Documents
- `citations`: chunk_id of a retrieved passage, a short quote (one sentence or clause, <= 200 characters) copied
  character-for-character from that passage, including capitalisation and spacing, and what it supports.
- `published_findings`: for a retrieved AEMO market notice for the same region and window, give the citation_id of
  your citation that quotes it. The controller renders the finding as that verbatim quote.
- Elsewhere, refer to a document by its citation id and keep its numbers, identifiers, dates and wording
  (including phrases such as "cause of") inside the quote. Write "AEMO reported a City West transformer trip
  [c1]", not "at 1140 hrs on 30/07/2026 transformer T_1 and breaker 6675 tripped".

Explanations and status
- `observation_evidence_ids`: evidence_ids of the key tool observations (the controller copies values and sources).
- `possible_explanations`: hedged hypotheses only ("may", "might", "could"), each with what would test it.
  `supporting_evidence_ids` lists only evidence_ids from tool results (it may be empty); mention related documents
  by citation id in the statement.
- Outside `possible_explanations`, do not use causal wording (caused, due to, because of, led to, resulted in,
  drove, triggered, responsible for).
- `status`: "answered" when required tools succeeded and the answer is evidence-backed; "answered_with_caveats" when
  some evidence is missing; "abstained" when the evidence cannot answer the question.
