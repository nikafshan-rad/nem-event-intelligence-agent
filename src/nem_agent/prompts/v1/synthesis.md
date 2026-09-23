Write the investigation report as JSON matching the schema. Use only evidence returned by the tools above.

- `numeric_claims`: one entry for every number that appears in headline, summary, possible_explanations or
  published_findings (outside verbatim quotes). Each has the value exactly as shown in your text (rounded as
  displayed), its unit, the `evidence_id` it came from and the rounding tolerance you applied.
- `observations`: list the evidence_ids of the key tool observations (the controller copies values and sources).
- `citations`: chunk_id of a retrieved passage, a VERBATIM quote from that passage (<= 400 characters), and what it supports.
- `possible_explanations`: hedged hypotheses only, each with supporting evidence ids and what would test it.
- `published_findings`: only verbatim statements from same-region, same-window AEMO market notices, with citation ids.
- `status`: "answered" when required tools succeeded and the answer is evidence-backed; "answered_with_caveats" when
  some evidence is missing; "abstained" when the evidence cannot answer the question.
