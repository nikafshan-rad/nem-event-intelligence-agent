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
- Terms that begin with a digit (5MPD, 30MPD) read as numbers: spell them out ("five-minute pre-dispatch").
- State numbers only for the investigated region.
- Forecast reviews: compare the context's `forecast_targets_utc` with compare_forecast_actual, and set
  `forecast_mae_evidence_id` to the evidence_id of the MAE you report (null for other questions).

Times
- Copy every clock time from a tool output or the context, with its zone: prefer a `*_local` field (e.g.
  "2026-07-31 02:05 ACST", from `event_peak_interval_end_local` or `interval_end_local`); timestamps ending in Z are
  UTC (write "16:35 UTC"). Never convert, shift or re-label a time yourself: the validator rejects any time that no
  tool returned.
- Do not describe a time as morning, afternoon, evening, night, daytime or similar: give the local clock time
  instead (a UTC clock time says nothing about the time of day in the region).
- Describe only what a tool field shows. Consecutive `hourly_samples` are an hour apart, not the intervals
  "immediately before and after" another; call intervals one episode only when a tool reports them as an episode
  (not "sustained" or "continuous" otherwise).
- This applies equally to `possible_explanations` and their `what_would_test_it`. Every clock time there carries its
  zone exactly as a tool returned it, and must be a time a tool returned. A notice's "HHMM hrs" is NEM time: use the
  `utc` or `local` value in that notice's `clock_times`, never the bare "HHMM". If a time cannot be stated that way,
  leave it out: write "the constraint notice [c1]", not "from 11:00".
- AEMO notices state times as "HHMM hrs" in NEM market time (UTC+10). Use each notice's `clock_times` (UTC and
  local equivalents) and compare times only on the same basis; never call two times coincident unless their UTC
  values show it.

Measures and forecast runs
- If the context has `requested_measures`, answer with exactly those measures, from the tool fields it names. Dispatch
  TOTALDEMAND (5-minute) and operational demand (half-hour) are different quantities: never give one when the
  question asks for the other. If the requested measure was not returned, say so in `missing_evidence`.
- If the context has `requested_forecast_run`, the question names a forecast by its issue time: use that run
  (compare_forecast_actual with run_selector "run_id"), and use actuals as usual. The issue time is not an as-of
  cutoff.

Documents
- `citations`: chunk_id of a retrieved passage, a short quote (one sentence or clause, <= 200 characters) copied
  character-for-character from that passage, including capitalisation and spacing, and what it supports. Documents
  are cited by citation_id; they have no evidence ids.
- For a document question the controller has already retrieved passages for the question itself (shown before the
  tools); use them, and search further when they do not answer it.
- Definition and document answers: write each sentence as an entry in `document_statements` (its citation_id and
  either `quote`, copied character-for-character from that passage, or `paraphrase`, a close restatement of only
  what the passage says) and leave `summary` empty. The controller writes each sentence with its [citation_id] and
  shows a quote in quotation marks only when it matches the passage exactly; a quote that does not match is shown as
  your own words and checked as such. Prefer a quote whenever the passage contains numbers or percentages.
- Event and forecast reviews: leave `document_statements` empty.
- If no retrieved passage answers the question, set status "abstained", leave `summary` and `document_statements`
  empty, and say in the headline and `missing_evidence` what was searched and what was not.
- Each retrieve_public_evidence result has a `search_scope`: market notices are searched only for the region and
  event window you give; the scope says whether they were searched, how many are held for that region and window,
  and how many were returned. Keep three cases apart: searched and a notice was found; searched and none is held;
  not searched (or not held locally). Never say that no notice exists for a region or window you did not search.
- When a question asks about other regions (e.g. regions other than the one named), those are the regions to
  search: call retrieve_public_evidence once for each requested region, with that region and the event window.
  Report per region what its notices say, or that none is held, or that it was not searched. A notice from another
  region is never a published finding for this region.
- `published_findings`: for a retrieved AEMO market notice for the same region and window, give the citation_id of
  your citation that quotes it. The controller renders the finding as that verbatim quote.
- Elsewhere, refer to a document by its citation id and keep its numbers, identifiers, dates and wording
  (including phrases such as "cause of") inside the quote. Write "AEMO reported a City West transformer trip
  [c1]", not "at 1140 hrs on 30/07/2026 transformer T_1 and breaker 6675 tripped".
- A quote is text inside double quotation marks ("..." or “...”) copied exactly. Text copied from a document
  without them counts as your own words, so its numbers must be registered claims; single quotes are not a quote.
- Market-event and forecast reviews: do not describe or quote market notices in the headline or summary. List each
  relevant notice under `published_findings`; the controller shows its verbatim text. In `possible_explanations`
  refer to a notice by its citation id and a few of its words, without its times, voltages or equipment numbers
  (e.g. "the Belalie-Davenport line outage notice [c2]").
- Definition and document answers: leave `possible_explanations` empty unless the question asks why something
  happened; a definition needs no hypotheses.

What a market-event review covers (the same content as the replay controller's report)
- The price extreme: its value and the local time of its interval end.
- How many 5-minute intervals met the analysis threshold, and the threshold.
- Actual operational demand (get_actual_demand) in the half-hour containing the price extreme (the context's
  `peak_half_hour_end_utc`), and the window's maximum operational demand. Dispatch TOTALDEMAND is a different
  measure: label it as such if you use it.
- AEMO market notices for the region and window, as published_findings; hedged explanations, each with a test.

Headline
- State the main finding with its key number and local time (e.g. the price extreme, the forecast error, or the
  definition in brief). Do not repeat the question.
- In a definition or document answer the headline has no citation: state the answer without the document's numbers
  or percentages (they appear only inside a quoted statement).

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
