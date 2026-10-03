# Issue tracker: Live answer defects

One list of known defects, so that each fix is weighed against the whole. Evidence comes from saved Live records
(`artifacts/live/`) unless a row says otherwise.
- **Priority:** P1 means the user's question goes unanswered or answered wrongly; P2 means the answer is right but hard
  to read or trust; P3 is a known, bounded limitation.
- **Paid checks:** a paid Live check runs after a meaningful group of fixes, not after each PR. Until then a fix is
  verified offline only.
- **Dated results:** each issue's "Result" section records its status when it merged. Live results measured later are
  in the Open table and the Completed table, and the original verdicts are never replaced. See "Evidence scope" under
  Next for what kind of evidence each run is.

## Open

| ID | Area | Concrete example | Priority | Status |
| --- | --- | --- | --- | --- |
| I-1 | **Direct, complete answers** | **(a)** F04 (live check 2026-09-29) asked "Was Directlink being out of service what drove the NSW1 price spike…?": the answer lists correct observations and hedged possibilities but never says what the evidence supports. **(b)** W19 (held-out v4) does not say the reserve (LOR) forecasts were cancelled before the day, and its hypotheses lean on them | P1 | **(a): fixed offline** in PR `#16`. **Live (development cases only, 2026-09-30): held** on F04 and W18. **(b): fixed offline** in PR `#17`. **Live (development case): failed** on W19: it triggered internally and the sentence was correct, but the answer fell back, so it was not displayed (I-6). The outcome stays failed. **Second development check (2026-09-30, PR `#28`, one run per case):** (a) held on F04, failed on W18 (the answer fell back; I-7); (b) **held** on W19 |
| I-2 | **Evidence selection and calculations** | **(a)** F04 never fetched the other regions' prices, so it misses that VIC1, SA1 and TAS1 were also above 470 $/MWh while QLD1 was about 65. **(b)** W04 gives both total-demand values (10046.72 and 11432.7 MW) but not the rise between them: a derived number has no evidence ID | P1 | **(a): fixed offline** in PR `#18`. **Live (development cases only, 2026-09-30): held** on F04 and W18. **(b): fixed offline** in PR `#19`; departs from checks 4 and 5 as written (below). **Live (development case): held** on W04. **Second development check (2026-09-30, PR `#28`, one run per case):** (a) held on F04, **failed** on W18 (the answer fell back; I-7); (b) not run (W04 was held back by the start guard) |
| I-3 | **Clear presentation** | F01 shows "New South Wales 150" without "MW". F03 shows "1630 hrs" without its zone (NEM time, 06:30 UTC). Headlines are vague or off the question: F03's after repair, F04's (the peak price). W04 and W18 (Live, 2026-09-30): the same value appears twice among the observations, and W04's headline has "(UTC+1000)". (W18's inconsistency is now I-7) | P2 | **(a) F03's notice time without a zone: fixed offline** in PR `#23` (below). **(b) F01's number without its unit: verified offline** (PR `#24`, below). **(c) headlines that do not answer the question: verified offline** (PR `#25`, below). **(d) duplicated values: verified offline** (PR `#26`, below). Each was Live-unverified when merged. **Second development check (2026-09-30, PR `#28`, one run per case):** (a) **held** on F03; (b) **held** on F01; (c) **held** on F03 and F04, failed on W18 (fell back); (d) **held** on W18 and W19. **Later display fixes, verified offline only (Live unverified):** "$845.0" without "/MWh" (I-3e, PR `#33`), repeated finding titles (I-3f, PR `#34`), raw passage IDs as citation markers (I-3g, PR `#35`) |
| I-4 | **Internal details in user-facing text** | Tool names (W20: "API functions named get_actual_demand / get_forecast_runs"), controller notes ("Market notices were not searched…" on document questions, F01), and evidence IDs (F04: "ev0878 … is not a time-stamped observation"). W04 (Live, 2026-09-30): "Controller-computed dispatch TOTALDEMAND (5-minute) change … [ev0975]" | P2 | **Verified offline** (PR `#27`, below). **Second development check (2026-09-30, PR `#28`, one run per case):** **held** on W18, W19 and F04; not triggered on F01 and F03 (nothing to rewrite). Found in that check: "(threshold ev0878)" became "(threshold the listed observation)" on F04, and model wording such as "returned to the controller" (W19) was not rewritten. **Both fixed later, verified offline only (Live unverified):** I-4b (PR `#31`) and I-4c (PR `#32`) |
| I-6 | **A valid controller answer lost to a fallback** | W19 (Live, 2026-09-30): the controller's cancellation sentence was correct, but the model's own lines quoted notice titles in single quotes ('… Lack Of Reserve Level 2 (LOR2) …'). `NUMERIC_UNTRACKED` counted the "2", and one line failed `TIME_NOT_IN_EVIDENCE`. The scoped repair did not clear them, so the answer fell back and nothing was shown | P1 | **fixed offline** in PR `#21` (below). The frozen run's outcome for W19 stays failed. **Second development check (2026-09-30, PR `#28`, one run per case):** **held** on W19: the model named cited notices by their exact titles, and the answer was shown with the cancellation sentence |
| I-7 | **An explanation kept open that the answer's own timing rules out** | W18 (Live, 2026-09-30): the opening says timing rules the Hazelwood bus-tie outage out. The notice gives 1100 hrs 20/08, after every high-price interval. A hedged hypothesis resting on that notice [c1] still offers it as a possible influence | P2 | **fixed offline** in PR `#22` (below); Live-unverified when merged. Offline, W18's actual saved repair now falls back, and only a scripted repair that deletes the hypothesis passes. W18's Live verdict (held) is unchanged. **Second development check (2026-09-30, PR `#28`, one run per case):** **failed** on W18: it fired on a hypothesis that doubted the post-event notice; the scoped repair turned that hypothesis into an unhedged statement (HYPOTHESIS_UNHEDGED), and the answer fell back. **I-7b** (a doubting hypothesis flagged; the repair's evidence-backed exclusion rejected as unhedged): **verified offline; Live unverified** (PR `#30`, below). The second check's W18 verdict stays failed; its passing offline replay does not replace it. **I-7c** (a validated exclusion shown apart from hypotheses): **verified offline; Live unverified** (PR `#36`, below) |
| I-8 | **A definition shown with its meaning reversed** | Y20 (held-out v5, Live, 2026-10-02): asked whether operational demand counts scheduled loads, the answer said it *includes* "local demand of scheduled loads and scheduled bidirectional units" [c1], citing figure text that subtracts them; the definition excludes them. It passed validation and was shown | P1 | **verified offline; Live unverified** (PR `#40`, below). v5's FAIL verdict and Y20's scores are unchanged. **Run A (2026-10-02, development case, one run, code `6413076`):** **not exercised**: Y20 fell back (`CITATION_QUOTE_NOT_FOUND`), so no definition was stated |
| I-9 | **The forecast run asked for, replaced by another** | Y05, Y06 (held-out v5, Live, 2026-10-02): asked for the last forecast issued before a named half-hour, both answers gave a run issued about three hours earlier (Y05 POE50 10,972 MW from the 17:56:59Z run instead of 11,082 from the 20:56:59Z run; Y06 2,017 from 04:27:00Z instead of 1,816 from 07:26:58Z), presented as the run asked for | P1 | **verified offline; Live unverified** (PR `#41`, merged as `0f0b5c9`; below). v5's FAIL verdict and Y05/Y06's scores are unchanged. **Run A (2026-10-02, development case, one run, code `6413076`):** **held** on Y05 and Y06 (the named runs' values). **Fresh question (held-out v6 Z05): failed**: the half-hour was not pinned down from the wording, so no run was bound and another run was used (now I-16) |
| I-10 | **An as-of forecast question sent back for a date it already gives** | Y07 (held-out v5, Live, 2026-10-02): "As of 2026-08-19T20:00:00Z, … what was the newest Victorian operational demand forecast for the 23:00 to 23:30 UTC half-hour …?" was answered with "Which date (or UTC window) should be investigated?". The explicit cutoff dates the question | P2 | **verified offline; Live unverified** (PR `#42`, merged as `1eb4484`; below). Date-inference limits remain: only forecast questions; a cutoff dates only a clock-only half-hour later on its own date; a cutoff without its date is sent back. v5's FAIL verdict and Y07's scores are unchanged. **Run A (2026-10-02, development case, one run, code `6413076`):** **held** on Y07 |
| I-11 | **A causal price-event question routed as a forecast question** | Y18 (held-out v5, Live, 2026-10-02): "Was AEMO's forecast lack of reserve the reason South Australia's price spiked at 07:55 UTC on 29 July 2026?" was routed as `forecast_review`. `find_market_events` was not run, the answer gave a forecast-error comparison, and it omitted that the day's reserve (LOR) notices were each cancelled beforehand | P2 | **verified offline; Live unverified** (PR `#43`, merged as `ad34e59`; below). The passing replay used W19's saved market-event tool calls and drafts under Y18's question and routing decision; Y18's own saved answer, replayed on the corrected route, still falls back (`NOTICE_TIMING_OMITTED`). v5's FAIL verdict and Y18's scores are unchanged. **Run A (2026-10-02, development case, one run, code `6413076`):** **held** on Y18: routed as an event review, `find_market_events` run, both cancelled reserve notices stated as cancelled |
| I-12 | **A quoted decision shown without the reason its notice gives** | Y14 (held-out v5, Live, 2026-10-02): asked "what was AEMO's decision on reclassifying" a Victorian network trip, the answer quoted notice 144667's decision, "AEMO will not reclassify this event as a credible contingency event." [c1], but not the sentence before it: "The cause of this non credible contingency event has been identified and AEMO is satisfied that another occurrence of this event is unlikely under the current circumstances." The check's two elements, cause identified and recurrence unlikely, were missing | P2 | **verified offline; Live unverified** (PR `#44`, merged as `7c83b04`; below). Adding the notice's stated basis for a quoted decision does not establish that every part of a question is covered: no check compares what a question asks for with what the answer gives. v5's FAIL verdict and Y14's scores are unchanged. **Run A (2026-10-02, development case, one run, code `6413076`):** **held** on Y14 |
| I-13 | **An out-of-scope request answered with a clarification instead of a refusal** | Y17 (held-out v5, Live, 2026-10-02): "… what price should I expect in SA next Wednesday evening, and should I offer my battery's output into that peak?" The routing model marked it out of scope (and missing a date), but the answer was "Clarification needed: Which date (or UTC window) should be investigated?", with no refusal | P1 | **verified offline; Live unverified** (PR `#45`, merged as `0ded19f`; below). The refusal depends on the routing model's out-of-scope flag; Replay mode is unchanged and still asks Y17 for a date (its keyword guard does not match the wording). v5's FAIL verdict and Y17's scores are unchanged. **Run A (2026-10-02, development case, one run, code `6413076`):** **held** on Y17: refused, with the generic reason |
| I-14 | **A cut-off model response accepted as finished** | Y02 (held-out v5, Live, 2026-10-02): the first draft quoted the retrieval tool's status text "no notice held for this region and window" as if it were source text (`QUOTE_NOT_IN_SOURCE`); the scoped repair then ran to `max_output_tokens` (16,000 output tokens, 384 of them reasoning, the rest whitespace) and the answer fell back. The controller ignores a response's `incomplete` status and parses its text: Y02's failed to parse, but a response cut off after its JSON closed is used as finished | P2 | **verified offline; Live unverified** (PR `#46`, merged as `6413076`; below). I-14 fixes the acceptance of incomplete responses: a response that did not finish is rejected. It does not make Y02 answer successfully; Y02 still falls back, because only a finished repair can correct its first draft. v5's FAIL verdict and Y02's scores are unchanged. **Run A (2026-10-02, development case, one run, code `6413076`):** **not exercised**: no response was cut off. Y02 answered without a fallback, but missed two requested prices |
| I-15 | **A number shown with another interval's time** | Z03 (held-out v6, Live, 2026-10-02): "… (half-hour ending 2026-08-06T03:00:00Z / 2026-08-06 13:00 AEST) was 1204.0 MW …". 1204.0 MW is the half-hour ending 13:00Z (`ev0917`, the evidence the claim cites); the source value at 03:00Z is 1147.0 MW (`ev0897`, returned in the same series). The answer passed validation and was shown | P1 | **verified offline; Live unverified** (PR `#51`, merged as `8752b3d`; below). Each traced number's stated time is now bound to the evidence supporting it; Z03's saved answer is rejected and falls back. Pairing a time with its number is lexical (limits below). v6's FAIL verdict and Z03's scores are unchanged. **Targeted Live check 2026-10-02 (code `cf9558e`, PR `#54`; overall FAIL):** in its 4 value-and-time answers (Z03, K01, K03, K04) the stated times were right and the check never had to fire; K02 was sent back after a routing cut-off; K01 and K03 state other numbers wrongly (a flow direction, a "Price extreme" label). Too small a sample to verify I-15 generally; not exercised as a blocker in Live |
| I-16 | **The forecast run asked for, not bound because its half-hour was not read** | Z05 (held-out v6, Live, 2026-10-02): "the half-hour finishing at 07:30 on 31 July in market time (UTC 2026-07-30T21:30:00Z) … the last forecast run issued ahead of that half-hour". The answer gave the run issued 18:27:01Z (POE50 10,954 MW, −224 MW), the latest available by the half-hour's end, as that run; the run asked for, issued 20:56:59Z, gave 11,082 MW against 11,178 | P1 | **verified offline; Live unverified** (PR `#52`, merged as `45e5203`; below). Z05's half-hour is now read and the run asked for bound: its saved answer is rejected and falls back. A run named relative to a half-hour that is not pinned down is sent back for it. v6's FAIL verdict and Z05's scores are unchanged. **Targeted Live check 2026-10-02 (code `cf9558e`, PR `#54`; overall FAIL): not held.** Wording outside its fixed set was not read ("issued ahead of it", "issued before it", am/pm half-hours), so no run was bound: K06 and K07 show another run as the one asked for, and K05 was sent back. Z05 was contained (the run asked for only) but fell back |
| I-17 | **A measure's requested maximum replaced by its value at the price peak and another measure's maximum** | Z04 (held-out v6, Live, 2026-10-02): "… when did TAS1 total demand peak and at what level?" for 29 July 2026 (Hobart time). The answer gave dispatch TOTALDEMAND at the price peak (1,321.81 MW, 20:05) and the maximum of operational demand (1,452 MW, half-hour ending 08:00). TOTALDEMAND's maximum, 1,367.32 MW in the interval ending 07:55, was retrieved but never given | P1 | **verified offline; Live unverified** (PR `#53`, merged as `cf9558e`; below). A requested maximum is now computed by code over the requested window, stated by the controller and required of the answer; Z04's answer gives 1,367.32 MW at 07:55, and substitutes stated as the peak are rejected. v6's FAIL verdict and Z04's scores are unchanged. **Targeted Live check 2026-10-02 (code `cf9558e`, PR `#54`; overall FAIL): not held.** "total demand highest" and "hit its highest point" were not read as maximum requests, so nothing was computed: K09 and K10 show wrong maxima. Where the wording was read, the maximum was supplied (Z04, K11) |
| I-18 | **Forecast-run and demand-maximum requests that silently skip their binding** | Targeted Live check 2026-10-02 (`docs/live-gates.md`): wording outside the fixed patterns ("issued ahead of it", "issued before it", am/pm half-hours, "total demand highest", "hit its highest point") left K05–K07, K09 and K10 unbound; K06, K07, K09 and K10 then showed another run or a wrong maximum, and nothing checked them | P1 | **merged as `f2455ca`; verified offline; Live unverified** (PR `#56`; below). Requests are resolved from the request, the question parsers and the routing model's grounded reading (prompts v12), with provenance; a detected request that is not bound is sent back; two bounded answer backstops (the demand-extreme backstop window- and coverage-checked before merging). With saved routes K06, K07, K09 and K10 are sent back; with *scripted* correct routing fields K05, K06, K09 and K10 are supplied and K07 is answered unavailable; extraction by the real routing model is unverified. **Live check of the routing extraction, 2026-10-03 (PR #57's frozen protocol): FAIL.** No wrong routing binding was observed in this sample of 42 (18 correct, 14 of them using the model's reading; containment 6 of 6), but 4 of 42 routing calls were cut off at the 2,000-token cap; K09 shows an incorrect maximum (X: its headline contradicts the controller's correct maximum); K05 has an H4 finding (its MAE window is misdescribed); and requests were over-clarified (Q11, Q12, Q14, Q15, Q22, Q23, and K10 end to end). The earlier check's FAIL verdict and all historical scores are unchanged |
| I-19 | **Answer text that contradicts the requested result the controller holds** | Live check of the v12 routing extraction (E-dev, 2026-10-03): K09's controller line gives the correct maximum (10954.2 MW, ending 19:05 AEST), but its headline gives 10,890.3 MW at 19:35 AEST as the answer, an explanation calls 19:35 the maximum, and two caveats deny the maximum is established. K07's correct "unavailable" answer names the requested half-hour (17:00–17:30 AEST) as "ending 17:00" in four items. Nothing checked either | P1 | **verified offline; Live unverified** (branch `fix/requested-result-text`, validator only; below). K09's and K07's saved drafts are rejected at exactly the contradicting items and fall back, with the rejected caveats not shown; faithful text, comparisons, neighbouring half-hours and data-quality caveats pass; only K09 and K07 change among the 267 saved replays. The checks are lexical (limits below). K05's aggregation coverage, routing truncation and over-clarification are queued separately. **Development model comparison, 2026-10-03 (PR #62's frozen protocol; development cases, one run each; not a verification):** the checks fired on K07, K09 and K11. Both models' K09 answers fell back, and each fallback kept a caveat denying the maximum in wording the check does not read ("rather than a proven global maximum"; "cannot be verified", 11 tokens after the maximum wording). The validator flagged neither; the independent reviewer read gpt-5-mini's as X with H4 = 1. Recorded, not fixed |
| I-20 | **An aggregate described as covering more than it was computed from** | Live check of the v12 routing extraction (E-dev, 2026-10-03): K05 says "the run's MAE for the 24-hour target window as 10.0 MW". The MAE (`ev0554`) is the mean over one paired half-hour (ending 08:00Z) of a 12-hour comparison window holding 24 target half-hours. The answer passed validation and was shown; the independent reviewer read H4 = 1 | P1 | **verified offline; Live unverified** (branch `fix/aggregate-coverage`; below). Aggregates over a window (`mae_mw`, `mean_error_mw`, `n_aligned_half_hours`, `mean_dispatch_rrp`) carry their coverage from their own inputs, and stated durations, counts and completeness are checked against it. K05's "24-hour target window" is rejected and a faithful description passes; among the 267 saved replays only K05 changes outcome (Z05 gains one true finding in a draft that already fell back). The check is lexical (limits below). Routing truncation and over-clarification are queued separately. **Development model comparison, 2026-10-03 (development cases, one run each; not a verification):** it fired on gpt-5-mini's K05 and K06 drafts, and both repairs passed (S) |
| I-21 | **A facts-only fallback that drops the computed requested result and keeps model notes that disown it** | Development model comparison (2026-10-03), K09 slots 53 and 54; the v12 check's K09 replayed on `main`: the fallback states no maximum (the controller's 10954.2 MW, ending 19:05 AEST, is only listed among other values) and keeps model notes that deny or replace it ("rather than a proven global maximum"; "cannot be verified"; "not used as tool-backed evidence"). The fallback passed its own validation; the independent reviewer read slot 53 as X with H4 = 1 | P1 | **verified offline; Live unverified** (branch `fix/fallback-requested-result`; below). In a fallback holding a complete, validated requested demand maximum, the controller's line stating it is kept (provenance recorded when the line is written, never found by its wording) and every model note is withheld, recorded verbatim in diagnostics; the answer stays a fallback. `REQUESTED_MAXIMUM_MISSING` now needs the maximum stated, not merely listed. Among 215 replayable saved records only the three K09 fallbacks change; no answer that is not a fallback changes. Slot 53's X (H4 = 1) and all historical scores are unchanged |
| I-5 | **Known safety-language limitations** | See the list below. Each is recorded with its risk. None is being worked on, to avoid an open-ended wording cycle | P3 | recorded; revisit only with a new concrete failure |

### I-1a: F04, the causal question not answered directly

**Root cause.** From the saved record `artifacts/live/live-check-2026-09-29/F04.json` and trace `tr-0417e1209f13`:
1. **Recognition.** The controller's test for "does something a market notice reports explain the event?"
   (`asks_if_notice_event_caused`) needs a causal word and an incident word. "drove" matched. "being out of service"
   matched no incident word, so no notice timing was computed and none was required.
2. **Conclusion.** Where the test does fire, the controller computes each notice's time against the event, and the
   answer must state that timing. Nothing turns the timing into what it supports. Saved answers state the timing and
   stop:
   - H13 and W19 lead with the peak price;
   - W18 says the outage was "after the price extreme" without concluding;
   - F04's first draft led with the peak price and put "records do not establish a causal relationship" only among
     the uncertainties.

**The evidence F04 had.** The Directlink notice gives 0700 hrs 27/07 (the outage began), 1700 hrs 31/07 (scheduled
end) and 1430 hrs 31/07 (return). The price extreme was the interval ending 07:30 AEST on 31/07. So the outage was in
effect at the extreme. Timing does not rule it out, and no retrieved record shows whether it was behind the price.
That is insufficient evidence, not a timing contradiction.

**Acceptance check** (offline, written before the code change):
1. F04's question is recognised as asking whether a notice-reported incident explains the event.
2. Replaying F04's saved tool calls and first draft, the displayed summary opens with a sentence built from the
   evidence:
   - it names the notice by what the question names (Directlink);
   - it gives the notice's earliest time with its zone and UTC, and says it is before the price extreme;
   - it says the timing does not rule it out, and that no retrieved record shows whether it was behind the price.
   - The answer passes validation with no fallback and no causal wording, and says nothing about the Avon–Marulan
     notice, which the question does not ask about.
3. A timing contradiction reads differently. Replaying W18 (the Hazelwood bus-tie outage at 11:00 AEST, after the 09:10
   price extreme), the opening sentence says timing rules it out.
4. There is no generic sentence:
   - non-causal event questions (W01, W02, W03, W16) are unchanged;
   - a causal question whose incident is in no retrieved notice gets no inserted sentence.
5. The Replay evaluation and the safety suite are unchanged.

**Result** (PR `#16`, offline; evidence in `artifacts/logs/causal_answer_*`). All five checks are met:
1. **Recognised:** the incident vocabulary gains "out of service", "not in service" and "returned/back to service".
   "offline" is left out, because a blind negative uses it for a commercial decision. The three blind paraphrase sets
   score exactly as before.
2. **F04's opening sentence:** "The records cannot settle this: the AEMO market notice that mentions Directlink gives
   2026-07-27 07:00 AEST (2026-07-26T21:00:00Z), before the price extreme (interval ending 2026-07-30T21:30:00Z =
   2026-07-31 07:30 AEST). Its timing does not rule it out, and no retrieved record shows that it was, or was not,
   behind the price."
   - No critical violation and no fallback.
   - The validator accepts the sentence as the required notice-timing statement.
3. **Contradiction:** W18 opens with "Timing rules this out: … mentions Hazelwood gives 2026-08-20 11:00 AEST …, after
   the price extreme (… 09:10 AEST), so what it reports came later."
4. **No sentence where the evidence gives none:**
   - W01, W02 and W03 (not causal);
   - W19 (causal, but it names nothing: its "reserve" notices include a cancellation, whose time is not the
     incident's);
   - a weather question;
   - a question naming Basslink, which no notice names.
5. **Unchanged:** the Replay evaluation (identical to `main`), the safety suite, and the data and corpus versions.

**Side effects:**
- **H13:** its old draft now meets the notice-timing requirement.
- **Wider recognition extends the existing requirement:** an answer that cites a notice must state its timing, and
  this now applies to "out of service" questions. An old draft that cites a notice without that, like the Basslink
  variant, is rejected; in Live the controller now passes the timing context to the model.
- **One existing test changed:** its question no longer names the incident, so it still exercises the omission path.

**Still open for I-1:**
- the headline still states the peak price (I-3);
- the cross-region comparison (I-2a);
- questions naming nothing get no sentence;
- only notice timing is used, not other evidence;
- **Live is unverified.**

### I-1b: W19, cancelled reserve forecasts not mentioned

**The approved evidence.** Checked against the pinned raw notices (SHA-256 equal to their pins): every forecast lack of
reserve (LOR) for SA on 29/07 was cancelled before that day.

| Forecast | Period on 29/07 (NEM time) | Cancelled by | Cancelled at (NEM time) |
| --- | --- | --- | --- |
| 144624, LOR2 | 10:30–12:00 | 144626 | 09:20, 27/07 |
| 144627, LOR2 | 16:00–16:30 | 144628 | 12:00, 27/07 |
| 144652, LOR1 | 07:00–12:00 and 17:00–22:30 | 144655 | 13:45, 28/07 |

144623 also cancels 144621, which is not in the approved selection. The price extreme was the interval ending 07:55Z
(17:25 ACST) on 29/07.

**Root cause.** From the saved record `artifacts/live/L3-holdout-v4/W19.json`:
- **Source availability:** not the cause. Every forecast and cancellation is in the approved corpus.
- **Retrieval: partly.** The model's one query (top 6) returned the three forecasts but only two of their three
  cancellations: 144626, which cancels 144624, was missed. No tool links a notice to the later notice that cancels it.
- **Synthesis: the main loss.** The model listed the two retrieved cancellations only as timing items ("The STPASA
  LOR2 cancellation notice gives 2026-07-27 11:30 ACST, before …"). It never said any forecast was cancelled. Two of
  its three hypotheses rely on the cancelled forecasts as active: "the short reserve quantities noted in … [c3] and
  [c1]".
- **Repair:** none ran.
- **Validation:** passed. No check knows that a cited notice was cancelled.

**Acceptance check** (offline, written before the code change):
1. **Retrieval:** replaying W19's own tool calls, the retrieve tool marks each forecast it returns as cancelled by the
   later notice that names it, and adds that notice (144626) when the query missed it. It does this only under the
   same eligibility rules, so a cancellation published after an as-of time is not revealed.
2. **The answer:** with W19's first draft, the displayed summary states, in a sentence the controller builds from the
   notices, that each cited forecast was cancelled before the price extreme. It gives when the forecast was issued and
   when it was cancelled, so the two are distinguished.
3. **No reliance on cancelled forecasts:** a hypothesis citing a cancelled forecast as if it were active is rejected.
   W19's two such hypotheses are rejected; its third, which cites no notice, is not. After a repair that drops them,
   the answer passes with no fallback.
4. **Controls:** each gets no sentence and no new violation:
   - a forecast still active as of a time before its cancellation was published;
   - a status notice that was never cancelled;
   - a SYNTHETIC uncancelled forecast;
   - unrelated event answers (W01–W03, W18, F04).
5. **Consistency with I-1a:** the timing answer from #16 never treats a cancellation, or a cancelled forecast, as the
   incident.
6. **Unchanged:** the Replay evaluation and the safety suite, or any change is explained.

**Result** (PR `#17`, offline; evidence in `artifacts/logs/cancelled_notice_*`). All six checks are met:
1. **Retrieval:** a notice that says it cancels another names it: 16 of the 198 corpus notices do, of five kinds
   (reserve forecasts, directions, interventions, settlement residues, reclassifications).
   - On W19's own query, the retrieve tool marks 144624, 144627 and 144652 as cancelled by 144626, 144628 and 144655,
     and adds 144626.
   - As of 23:00Z on 26/07, 144624 shows no cancellation, and 144626 is not returned.
2. **The answer:** W19's answer opens with "AEMO later cancelled what these cited notices announced, each before the
   price extreme (interval ending 2026-07-29T07:55:00Z = 2026-07-29 17:25 ACST): the reserve notice issued 2026-07-27
   07:21 ACST … was cancelled by one issued 2026-07-27 08:57 ACST …; …".
3. **No reliance on cancelled forecasts:** W19's two hypotheses resting on cancelled forecasts get
   `CANCELLED_NOTICE_AS_ACTIVE`; the third, which cites no notice, does not. The answer fails closed if the repair
   repeats them, and passes with no fallback after a scoped repair deletes them.
4. **Controls:** none gets a sentence or a violation:
   - an active SYNTHETIC forecast;
   - one cancelled only after the price extreme;
   - a hypothesis that says the forecast was cancelled;
   - W01, W02, W03, W18 and F04.
5. **Consistency with I-1a:** a question naming the cancelled "LOR2" forecast no longer gets a "cannot settle" timing
   sentence built from a cancelled forecast's time.
6. **Unchanged:** the Replay evaluation is identical to `main`; the safety suite passes.

**Still open for I-1b:**
- only explicit cancellations count ("is cancelled", "cancelled from", "ceased", or a title with "Cancellation"),
  not other status changes (an updated or revised notice);
- the sentence gives issue and cancellation times, but not the forecast period;
- the facts-only fallback drops the sentence with the rest of the narrative;
- **Live is unverified.**

### I-2a: F04, the relevant regional comparison not made

**The comparison needed.** F04 asks whether Directlink, the interconnector between NSW and Queensland, being out of
service drove the NSW1 spike at 07:30 AEST on 31/07. The frozen check expects the prices of the other regions in the
same interval.

**The approved data supports it.** One approved dispatch file holds every region's price for the price extreme's
interval (ending 2026-07-30T21:30:00Z), with source rows `DISPATCHIS:…_202607310730_…:L5`–`L9`. Each row was published
21:25:09Z and became available 22:18:09Z.

| Region | Price ($/MWh) |
| --- | --- |
| NSW1 | 531.84849 |
| QLD1 | **64.95** |
| SA1 | 534.17438 |
| TAS1 | 478.08045 |
| VIC1 | 529.63 |

Every region's price series covers 27/07–20/08.

**Root cause.** From F04's saved record and trace `tr-0417e1209f13`:
- **Tool selection:** the model made one parallel round of tool calls, all for NSW1, then stopped.
  - The price tool takes one region per call.
  - The dispatcher caps it at 3 calls, whether the model or the controller makes them, so it cannot cover the four
    other regions.
  - Nothing asks for other regions, and no controller step fetches them.
- **Synthesis and validation:** with no other region's price in evidence, the answer could not state the comparison,
  and no check expects one.
- **What has to stay intact:** `CLAIM_REGION_MISMATCH` rejects any numeric claim about another region. It protects
  against mixing regions, and must stay.

**Acceptance check** (offline, written before the code change):
1. **Relevance and bounds:** the regional comparison is fetched only when the question is about an event and does one
   of these:
   - names another region;
   - uses inter-regional wording (interconnector, imports, other regions); or
   - names something a retrieved inter-regional-transfer notice names, as F04's "Directlink" and W18's "Hazelwood" do.

   It is one controller call, limited to the price extreme's interval. The model can neither see nor call it.
   W01, W02, W03 and W19 get no call.
2. **F04, offline replay** (saved tool calls and first draft):
   - the answer states that at the price extreme's interval SA1, TAS1 and VIC1 were also at or above the analysis
     threshold and QLD1 was below it, with no numbers in that sentence and no causal wording;
   - each other region's price is shown as an observation with its evidence ID and source row;
   - it passes validation with no fallback;
   - the I-1a timing answer still opens the summary;
   - `CLAIM_REGION_MISMATCH` is unchanged.
3. **As-of and unavailable data:** as of a time before the rows became available (22:18:09Z), no regional price is
   returned, so there is no sentence and no observation. A region without a row is left out.
4. **I-1a and I-1b still hold:** the F04 and W18 timing answers, and W19's cancellation sentence and rejections.
5. **Unchanged:** the Replay evaluation and the safety suite, or any change is explained.

**Result** (PR `#18`, offline; evidence in `artifacts/logs/regional_comparison_*`). The checks are met, with one change
to check 1 (below).
1. **Relevance and bounds:** F04 ("Directlink") and W18 ("Hazelwood"), both named in inter-regional-transfer notices,
   get exactly one controller call.
   - The tool is in a separate controller registry. The model's tool surface stays the 8 read-only tools (the security
     tests are unchanged), and a model call to it is an unknown tool.
   - W01, W02, W03 and W19, and an F04 question that names nothing, get no call.
   - **Change to check 1:** the "names another region" criterion was dropped. Such a question is already asked to
     choose one region before any evidence is gathered, so it could never apply. Inter-regional wording ("… also seen
     in the other regions?") still makes a question relevant.
2. **F04:** after the I-1a timing answer, the summary says "At the price extreme's 5-minute interval (interval ending
   2026-07-30T21:30:00Z = 2026-07-31 07:30 AEST), SA1, TAS1 and VIC1 were also at or above the analysis threshold, and
   QLD1 was below it."
   - The observations show QLD1 64.95, SA1 534.17438, TAS1 478.08045 and VIC1 529.63 $/MWh, each with its evidence
     ID and source row (`…_202607310730_…:L6`–`L9`).
   - No causal wording, no fallback.
   - A model claim on another region's price still gets `CLAIM_REGION_MISMATCH`.
3. **As-of and unavailable data:** as of 22:00Z (the rows became available 22:18:09Z), no price is returned, so there
   is no sentence and no observation. An interval with no data returns nothing.
4. **I-1a and I-1b still hold:** F04's and W18's timing answers, and W19's cancellation sentence and rejections, are
   unchanged. Their tests pass.
5. **Unchanged:** the Replay evaluation (identical to `main`) and the safety suite.

**Still open for I-2a:**
- only the price extreme's interval is compared, not the whole episode;
- interconnector flows are not fetched;
- relevance depends on a retrieved inter-regional-transfer notice or explicit wording, so an interconnector named only
  in the question, with no such notice public (for example in an as-of view), is not recognised;
- the model does not see the comparison;
- **Live is unverified.**

### I-2b: W04, the rise between two demand values left implicit

**The question.** "NSW, 31 July 2026: by how much did regional total demand climb from the 06:30 AEST dispatch interval
to the 07:30 AEST one, and what was the RRP at 07:30?" The frozen check expects about 10047 MW and about 11433 MW, "a
rise of roughly 1386 MW", and the 531.85 $/MWh price.

**The two values are comparable.** Both are the same measure (dispatch TOTALDEMAND, `dispatch_totaldemand`), for the
same region (NSW1), at the ends of two 5-minute intervals. The rise is 11432.7 − 10046.72 = **1385.98 MW**.

| Value | Interval ending | Evidence | Approved source row |
| --- | --- | --- | --- |
| 10046.72 MW | 2026-07-30T20:30:00Z = 06:30 AEST | `ev0002` | `DISPATCHIS:…_202607310630_…:L20` |
| 11432.7 MW | 2026-07-30T21:30:00Z = 07:30 AEST | `ev0038` | `DISPATCHIS:…_202607310730_…:L11` |

**Root cause.** From `artifacts/live/L3-holdout-v4/W04.json`:
- **Evidence and tool selection: not the cause.** One price-timeline call returned both values. The answer cites them
  as claims, and lists operational demand (a different, half-hour measure) separately without mixing the two.
- **Synthesis: where the difference was lost, by design.** The system prompt says "Never do arithmetic yourself; use
  values the tools computed". No tool or controller step computes the change between two registered values. So the
  model gave both values and stopped.
- **Validation:** a number the model computed itself would have no evidence ID, and `NUMERIC_UNTRACKED` rejects it.
- **Repair:** none ran.

**Acceptance check** (offline, written before the code change):
1. **When the rise is computed:** a question asks by how much a measure changed, and between two times it names. The
   code then computes the change from the two registered values of the one demand measure the question names, in that
   region, at the two interval ends named, with the same interval length. The model does no arithmetic.
2. **The derived value:** it is registered as derived evidence linked to both source rows, with the derivation stated.
   Its as-of availability is the later of the two.
3. **W04's displayed answer:** it opens with a controller sentence giving the rise in MW (1385.98), both values, and
   both interval ends with zone and UTC. Each number is traced: the rise to the derived evidence, the two values to
   their own. It uses no causal wording, and passes with no fallback.
4. **Controls** (no sentence, no derived value, no new violation):
   - one of the two values missing, or published after the as-of cutoff;
   - the question naming operational demand, or both measures, where no pair is mixed;
   - a named time with no value of that measure (not an interval end);
   - a question asking no change;
   - a fall, which is stated as a fall.
5. **Unchanged:** the I-2a (F04) comparison, the I-1b (W19) cancellation and the I-1a timing answers; the Replay
   evaluation; the safety suite.

**Result** (PR `#19`, offline; evidence in `artifacts/logs/derived_change_*`). Checks 1–3 are met. **Checks 4 and 5
are not met as written:** one item of each departs from the check above, which is unchanged since `609fa30`. Both
departures are set out under "Departures from the pre-registered check" below, for the reviewer to accept or reject.
1. **When:** the question needs change wording ("by how much", "how much did … rise/fall/change", "the change in …
   from"), exactly one demand measure, and exactly two named times. Times are ISO timestamps, or clock times on the
   question's date in the zone they state (AEST, "market time", UTC …), else the region's local time. As-of cutoffs
   and issue times are not counted. Each time must be the interval end of exactly one registered value of that
   measure, in that region. The code subtracts the earlier value from the later; the model does no arithmetic.
2. **The derived value:** it is registered as derived evidence (`<metric>_change`), linked to both source rows, and
   its derivation names both evidence IDs. Its availability is the later of the two.
   - **Source availability:** `get_price_timeline` now registers each TOTALDEMAND value with its own row's publication
     and availability times. Before, it registered none, so no as-of check could see them.
   - **As-of guard:** a value not public by the cutoff is never used. The dispatcher already applies the cutoff to
     every call, and the controller checks again.
3. **W04:** the summary opens with "Dispatch total demand (TOTALDEMAND) rose by 1385.98 MW, from 10046.72 MW in the
   5-minute interval ending 2026-07-30T20:30:00Z = 2026-07-31 06:30 AEST to 11432.7 MW in the 5-minute interval ending
   2026-07-30T21:30:00Z = 2026-07-31 07:30 AEST."
   - The rise is traced to the derived value (rows `…_202607310630_…:L20` and `…_202607310730_…:L11`), each value to
     its own evidence.
   - No causal wording, no repair, no fallback.
   - The model is shown the computed change and its evidence ID before it writes, as with notice timing, and is told
     not to compute any difference itself.
4. **Controls:** no sentence and no derived value when:
   - a named time has no value of that measure: 08:00 AEST is outside the price timeline fetched, and the operational
     demand value that exists then is not used instead;
   - a time is not an interval end (06:32 for total demand, 06:45 for operational demand);
   - the question names both measures, or neither ("demand");
   - the question names one time, or asks for the values but no change;
   - it is as of 22:00Z, before the 07:30 AEST value was public;
   - (added) the question is about a forecast.
   - **A fall** is stated as a fall: "fell by 75.03 MW" from 07:30 to 07:35 AEST.
   - **Operational demand alone:** a sentence and a derived value, against the check as written (departure A below).
5. **Unchanged:**
   - **Replays:** 22 saved records (W01–W20 and F01–F04; W16 and W17 have no draft) were replayed on `main` and on
     this branch. All but W04 are identical, including F04's comparison and timing answer and W19's cancellation
     sentence.
   - **Replay evaluation:** PASS. The agent's rows, gates and failures are identical to `main`'s. One baseline number
     changes, against the check as written (departure B below).
   - **Safety suite:** PASS.

**Departures from the pre-registered check** (decided while implementing, after the check was written):

**A. Check 4, operational demand.** As written: "4. **Controls** (no sentence, no derived value, no new violation):
… the question naming operational demand, or both measures, where no pair is mixed".
- **Both measures:** met. No sentence and no derived value.
- **Operational demand alone: not met.**
  - The question: "…by how much did regional operational demand climb from the 06:30 AEST half-hour to the 07:30
    AEST one?"
  - The sentence it gets: "Actual operational demand rose by 1426 MW, from 9752 MW in the half-hour ending
    2026-07-30T20:30:00Z = 2026-07-31 06:30 AEST to 11178 MW in the half-hour ending 2026-07-30T21:30:00Z =
    2026-07-31 07:30 AEST."
  - The derived value it gets: `opdemand_actual_change` = 1426 MW, `ev0050` minus `ev0048`, from two
    `OPDEM_ACTUAL_DAILY` rows only.
  - It passes with no new violation and no fallback.
- **Why:** read literally, check 4 contradicts check 1. Check 1 requires the change "from the two registered values
  of the one demand measure the question names". The implementation follows check 1, and keeps what check 4 guards
  against: the two measures are never paired.
- **If check 4 is held as written:** operational-demand questions must be excluded. That code change is not made
  here.

**B. Check 5, the Replay evaluation.** As written: "5. **Unchanged:** … the Replay evaluation; the safety suite." It
has no "or any change is explained" clause, unlike I-2a's.
- **The agent:** its rows, gates and failures are identical to `main`'s, with 0 as-of leaks.
- **Not met: the chart-and-table baseline's as-of leak count rises from 1245 to 2130.**
  - That baseline fetches with no cutoff, and counts every item not yet public by the case's cutoff.
  - Its TOTALDEMAND items had no publication time, so they could not be counted. They now carry their row's own.
  - The +885 are all TOTALDEMAND values (FC02 +183, FC08 +226, AMB06 +286, ADV03 +190), at exactly the intervals
    whose price it already leaked. Every other metric's count is unchanged.
  - No criterion, threshold or gate changed. The baseline still cannot count its early net-interchange values.
- **The agent cannot show a TOTALDEMAND value early:**
  - **The price tool** filters on each interval's availability. Ingest gives the price row and the demand row the
    same availability, because both come from one dispatch file. Over 11,310 calls it returned 616,700 values, none
    after the cutoff.
  - **The dispatcher** applies the request's cutoff to every call, and blocks a later one.
  - **The Replay agent** (24 runs with cutoffs, 3,444 values) and **the W04 Live replay** (cutoffs around 22:18:09Z)
    registered and showed none after the cutoff.
  - **The validator** can now flag a TOTALDEMAND claim made after the cutoff. On `main` it could not.
- **Evidence:** `artifacts/logs/derived_change_deviations_review.log` and
  `artifacts/logs/derived_change_eval_vs_main.log`.

**Still open for I-2b:**
- only changes between two named times, of total or operational demand; not prices or other measures, and not
  "demand" left unqualified;
- clock times need hours and minutes ("7:30 am", not "7 am");
- net interchange values still carry no publication time, the gap total demand had; the dispatcher's cutoff still
  applies to the calls that fetch them;
- the price tool's cutoff covers a demand value only because ingest gives it its price row's times (true for all 7350
  joined rows); a source that published the two separately would need its own filter;
- the model's own text may still restate or contradict the change;
- **Live is unverified.**

### I-6: W19, a valid controller answer lost to a fallback

**What happened** (Live, 2026-09-30, `artifacts/live/live-check-p1-dev/W19.json`, trace `tr-b09af6da7d95`):
- **The controller's sentence:** it was correct; the cancellation sentence named 144624, 144627 and 144652 with their
  exact times.
- **The fallback:** after one scoped repair, the answer still failed validation and fell back to facts only. So the
  sentence was not displayed. The run's outcome stays **failed**.

**Root cause.** The numeric check (`narrative_numbers`) serves `NUMERIC_UNTRACKED`, the interval check and the time
check. It reads the digits inside notice titles as numbers.
- **What it already skips:** text in double quotes, system IDs, and identifier patterns ("LOR2" is already one).
- **What it misses:** a title in single quotes. So the "2" of "Level 2" and the "1" of "Level 1" count as numbers.
- **The repaired draft:**
  - four lines quote 'STPASA - (Cancellation of the) Forecast Lack Of Reserve Level 2 (LOR2) in the SA Region on
    29/07/2026'. The "2" matches no claim, so `NUMERIC_UNTRACKED`;
  - one line quotes '… Level 1 (LOR1) …'. The "1" happens to equal an unrelated claim (1 interval at 07:55Z), which
    ties the line to 07:55Z. Its notice times then fail `TIME_NOT_IN_EVIDENCE`.
- **The titles are exact:** each is the retrieved notice's own title. That is the chunk title after "AEMO market notice
  N (SECTION): ", and the start of the notice text.
- **Not the cause:** the controller sentence, retrieval, and tool selection.
- **The first draft's other two faults were genuine** (a contradicted notice timing, and "29 July" without a year),
  and the repair fixed them.

**Acceptance check** (offline, written before the code change):
1. **Recognised as title text:** an exact title of a market notice retrieved in this investigation. The notice must be
   eligible and not flagged as instruction-like, and the title at least 4 words. Wherever it appears in narrative
   text, its digits are not read as numbers.
2. **Still rejected:**
   - a number outside the title, in the same sentence;
   - an altered title (a changed digit or word);
   - an invented title;
   - the title of a notice not retrieved in this investigation;
   - the title of an ineligible or instruction-like passage;
   - a shortened title;
   - an unsupported numeric claim (claims are checked as before).
3. **W19 replay:** use the Live run's saved tool calls, first draft and saved repair patch.
   - **This branch:** the answer passes after the repair, with no fallback, and the cancellation sentence is displayed.
   - **Before the fix:** the same replay falls back with `NUMERIC_UNTRACKED` and `TIME_NOT_IN_EVIDENCE`, as in Live.
4. **Unchanged:** the Replay evaluation, the safety suite and the other saved replays. The frozen run's outcome for W19
   stays failed. PR #20 is unchanged.

**Result** (PR `#21`, offline; evidence in `artifacts/logs/notice_title_numbers_*` and
`artifacts/logs/notice_title_citation_bypass.log`). All four checks are met. Check 1 was tightened after review (below).
1. **Recognised:**
   - `notice_titles(registry, chunk_ids)` collects each eligible, unflagged market notice's own title: the chunk title
     after "AEMO market notice N (SECTION): ", of at least 4 words.
   - **Tightened after review of PR #21:** check 1 exempted the title of any retrieved notice. Review asked whether a
     title with no citation, or next to a citation to another notice, could bypass the numeric check. Both could
     (`notice_title_citation_bypass.log`). Now a title counts only where a matching cited notice supports it:
     - **A line without citation markers:** the report must cite that notice. This is W19's form.
     - **A line with markers:** one of them must point to that notice, by citation ID or by the cited passage's ID.
     - **Other markers:** evidence markers (`[ev0436]`) are not citations. A marker to anything the report does not
       cite gives no cover.
     - **Stricter only:** a title of a retrieved but uncited notice, or one next to a citation of another notice, is
       read like any other text.
   - `narrative_numbers` removes a title only where it appears whole: not inside a longer number, and after the same
     hyphen normalisation the rest of the text gets.
   - All three uses of the numeric reader get the titles: untracked numbers, intervals and times.
2. **Still rejected, each tested:**
   - a number outside the title;
   - an altered digit or word;
   - a shortened or invented title;
   - a title followed by more digits;
   - the title of a notice not retrieved, ineligible or flagged, even when cited;
   - the title of a notice retrieved but not cited;
   - a title in a line citing only another notice, even when the titled notice is cited elsewhere;
   - a title in a line whose marker points to nothing the report cites;
   - numeric claims, which are unchanged (`CLAIM_VALUE_MISMATCH` and `CLAIM_EVIDENCE_MISSING` still fire).
3. **W19 replay:**
   - **Before the fix:** it falls back as in Live. After the repair, 4 × `NUMERIC_UNTRACKED` ("2") and
     `TIME_NOT_IN_EVIDENCE` remain.
   - **With it:** only the first draft's two genuine faults are caught (the contradicted notice timing, and "29").
     After the repair the answer passes, with no fallback, and opens with the cancellation sentence, identical to the
     one the Live run built.
   - **The tightened rule gives the same result,** because W19's lines have no citation markers and the report cites
     every notice they name.
   - **A title altered to "Level 3 (LOR3)", or a "2 MW" added outside a title,** still falls back.
4. **Unchanged:**
   - **Replays:** 25 of 26 saved replays are identical, and only the 2026-09-30 W19 run changes.
   - **Replay evaluation:** identical to the base in every section.
   - **Safety suite:** PASS.
   - **Tests:** 574 pass, 30 of them new.
     - **On the base:** 17 of the new tests fail, and the 13 "still rejected" controls pass.
     - **On PR #21 as first proposed:** 7 fail, the 6 bypass cases and the new function signature.
   - **The frozen Live run's outcome for W19** stays failed.

**Still open for I-6:**
- only a cited market notice's own title is recognised, not the "AEMO market notice N (SECTION): " prefix (its notice
  number is still read as a number), a partial title, or the title of another document type;
- **Report-level support:** a line without markers is supported by a citation anywhere in the report. Requiring a
  marker in the line itself would leave W19's answer falling back, because its lines carry none;
- single-quoted text is otherwise read as before;
- **Live is unverified.** A paid re-check of W19 would be development evidence only, and needs approval.

### I-7: W18, an explanation its own timing rules out

**What happened** (Live, 2026-09-30, `artifacts/live/live-check-p1-dev/W18.json`, trace `tr-37d19c4380bd`):
- **The opening:** the controller's timing answer says "Timing rules this out": the AEMO market notice that mentions
  Hazelwood gives 11:00 AEST on 20/08, after the price extreme (09:10 AEST).
- **The hypothesis:** the answer's `possible_explanations[1]` still offers the Hazelwood bus-tie notice [c1] as
  something that "might have limited local transfer capability and so could have influenced prices".
- **The outcome:** W18 is held under the frozen rule, because a hedged hypothesis states no cause as fact (recheck in
  `REVIEW.md`).

**The evidence.**
- **The notice:** `market_notice_144893` states one time, 1100 hrs 20/08/2026 = 2026-08-20T01:00Z.
- **The event:** VIC1's six intervals at or above 300 $/MWh in the window end between 23:05Z and 23:45Z on 19/08.
- **So:** the notice's time is after every high-price interval, and the incident cannot explain any part of the event.

**Root cause** (reproduced offline from the saved calls, first draft and repair patch; the replay passes on `main`):
- **Given, not used:** before writing, the model received the controller's notice timing, which puts the notice
  "after the price extreme" and is required in the summary. It still kept the hypothesis.
- **The repair kept it:** the one scoped repair rewrote this hypothesis for other faults (untracked numbers, times) and
  kept the notice as a possible influence.
- **No check:** nothing rejects a hypothesis resting on a cited notice whose time rules it out. The analogous rule
  exists only for cancelled notices (I-1b, `CANCELLED_NOTICE_AS_ACTIVE`).

**Acceptance check** (offline, written before the code change):
1. **Rejected:** a possible explanation that cites a market notice for the answer's region is rejected (critical). This
   applies when:
   - the notice's earliest stated time is after every interval of the event beyond the threshold (at or above it for a
     high-price event, below it for a low-price one);
   - the prices are registered up to that time.

   It is aimed at that hypothesis, so one scoped repair can drop it. A hypothesis saying that the timing rules it out
   is allowed.
2. **Controls,** with no new violation:
   - **Genuinely uncertain timing:** a notice with no stated time; a notice time within or before a later high-price
     interval; prices not registered up to the notice time;
   - **An incident before the event:** F04's Directlink notice, 0700 hrs 27/07;
   - **Unrelated hypotheses:** W18's other two;
   - **Other cases:** a hypothesis citing the notice to say its timing rules it out; another region's notice.
3. **W18 replay:**
   - **The flag:** the rule flags `possible_explanations[1]`.
   - **With a repair that deletes it:** the answer passes, with no fallback, and still opens with the timing answer
     and the regional sentence.
   - **With the saved Live repair patch,** which was not asked about this, the answer falls back. That is recorded as
     the risk.
4. **Unchanged:** F04 and W19 (their 2026-09-30 replays and earlier records), the Replay evaluation (or any change is
   explained) and the safety suite.
   - **Not covered:** caveat lines. W18's `missing_evidence[1]` asks for timestamps "to confirm whether the outage began
     before or after" the peak. It is a request for evidence, not an explanation, and cites nothing.
   - **Verdicts:** W19's Live verdict stays failed, and W18's stays held.

**Result** (PR `#22`, offline; evidence in `artifacts/logs/ruled_out_explanations_*`). All four checks are met.
1. **Rejected:** a new critical check, `EXPLANATION_RULED_OUT_BY_TIMING`, next to `CANCELLED_NOTICE_AS_ACTIVE`.
   - **It fires when** a possible explanation cites a market notice for the answer's region, and the notice's earliest
     stated time (as the notice-timing check parses it) is after every interval of the event beyond the threshold.
   - **Only if** the prices are registered, without gaps, up to that time or the window's end.
   - **It names the hypothesis,** so one scoped repair can drop it.
   - **It is not triggered** by a hypothesis saying the timing rules it out ("rules this out", "ruled out", "could not
     have").
2. **Controls, each tested,** with no violation:
   - a notice with no stated time;
   - a notice timed after the price extreme but before later high-price intervals;
   - a later notice when the prices are not registered up to it;
   - an incident before the event;
   - another region's notice;
   - unrelated hypotheses;
   - hypotheses saying the timing rules the explanation out.
3. **W18 replay:**
   - **On `main`:** it passes with the Hazelwood hypothesis shown.
   - **Here, with the Live repair deleting that hypothesis:** it passes with no fallback. The answer opens with the
     timing answer and the regional sentence, and keeps its two unrelated hypotheses.
   - **With the saved Live patch,** which rewrote the hypothesis and kept [c1], the answer falls back.
4. **Unchanged:**
   - **F04 and W19** (their 2026-09-30 records and F04's 2026-09-29 record) raise no new violation, and their answers
     are unchanged.
   - **Replays:** 25 of 26 saved replays are identical; only W18's 2026-09-30 replay changes.
   - **Replay evaluation:** identical to `main` in every result section.
   - **Safety suite:** PASS.
   - **Tests:** 589 pass (15 new; on `main` the 3 that expect the rejection fail, and the 12 controls pass).

**Still open for I-7:**
- **Fallback risk:** if a Live repair rewrites the hypothesis but keeps the notice, the answer falls back rather than
  showing the contradiction. The repair prompt names the hypothesis and says "drop it, or say that the timing rules it
  out", but how the model responds is unverified.
- **Not covered:**
  - a notice timed after the price extreme but within the event, where an explanation of the later intervals stays
    possible;
  - caveat lines (W18's `missing_evidence[1]`);
  - a hypothesis naming the incident without citing the notice.
- **Live is unverified.**

### I-7b: W18 (second check), a doubting hypothesis flagged, and the exclusion its repair wrote rejected as unhedged

**What happened** (Live, second development check, 2026-09-30, `artifacts/live/live-check-dev2/W18.json`, trace
`tr-68178b00c1f1`; reproduced offline from the run's saved first draft and actual repair patch, with the same
fallback):
- **The first draft's `possible_explanations[0]`:** "The Hazelwood PS 4 6 bus‑tie outage notice [c1] might refer to a
  later, separate outage and therefore might not correspond to the 2026-08-19T23:10:00Z price spike".
  - **I-7 flagged it** (EXPLANATION_RULED_OUT_BY_TIMING), because it cites a notice whose only stated time (01:00Z on
    20/08) is after every high-price interval.
  - **Yet it doubts the incident's bearing on the event;** it does not offer it as an influence.
- **The actual repair:** the one scoped repair followed I-7's message ("drop it, or say that the timing rules it
  out"). It replaced the item with "…that timing is after every five-minute interval at-or-above the $300.0 $/MWh
  analysis threshold …, so the notice's timing rules it out as an explanation for the price extreme".
- **The outcome:** HYPOTHESIS_UNHEDGED rejected that sentence ("a hypothesis must be hedged"). It was the only
  violation left, so the answer fell back. The fallback also withheld the controller's correct "Timing rules this out"
  headline.

**Root cause.**
- **I-7 counts any citation as reliance.** Apart from explicit "rules out" / "could not have" wording, it flags every
  hypothesis that cites the post-event notice, including one that only denies or doubts the incident's bearing.
- **I-7's own remedy fails the hedging check.** HYPOTHESIS_UNHEDGED requires a hedge word in every possible
  explanation, so the remedy I-7 asks for, stating that the timing rules the incident out, can never pass. For an
  exclusion backed by the validated notice timing, the two checks contradict each other.

**Acceptance check** (offline, written before the code change):
1. **I-7 flags reliance, not doubt.** A possible explanation citing a notice that meets I-7's timing condition is
   still EXPLANATION_RULED_OUT_BY_TIMING when it suggests the incident had any bearing on the event: "might have
   limited transfer capability and so could have influenced prices", "might be a factor", or a sentence that doubts
   one part and suggests another ("did not affect the first interval but could have influenced the peak"). It is not
   flagged when it only denies or doubts that bearing ("might not correspond to the price spike", "is unrelated to
   it"), or states that the timing rules it out (as before).
2. **An evidence-backed exclusion needs no hedge word.**
   - **What counts:** a possible explanation stating that the timing rules the incident out ("rules … out", "could
     not have"), where every market notice it cites meets I-7's timing condition. That is, each notice's earliest
     stated time is after every interval of the event beyond the threshold, and the prices are registered up to that
     time.
   - **Still checked:**
     - **Asserted causal wording:** HYPOTHESIS_UNHEDGED. It is found clause by clause, as in caveats, so "…rules
       Hazelwood out; wind caused the spike" is still rejected.
     - **Everything else:** overconfident wording, numbers, times, citations and the notice-timing check, unchanged.
   - **No exemption without that evidence:** a notice with no stated time, a time before or within the event, prices
     not registered up to it, or no cited notice. There, "rules it out" still needs hedging.
3. **Controls, each tested:**
   - **Uncertain timing:** no stated time; a notice time within the event; prices not registered.
   - **An incident before the event:** F04's Directlink notice.
   - **Unsupported causal claims:** "the outage caused the spike [c1]"; an exclusion followed by an asserted cause.
   - **Unrelated hypotheses:** an unhedged one is still HYPOTHESIS_UNHEDGED; a hedged one is unchanged.
   - **I-7's original case:** W18's 2026-09-30 first-check hypothesis, "might have limited local transfer capability
     and so could have influenced prices", is still flagged.
4. **Replays** (saved Live material through the fake transport; results from the actual saved repair are reported
   separately from any scripted alternative):
   - **W18, second check, with its saved first draft and actual repair:** on `main` it falls back with
     HYPOTHESIS_UNHEDGED, as in Live. With the fix, the answer is shown: the headline "Timing rules this out", with the
     exclusion as a possible explanation.
   - **W18, first check (2026-09-30), with its actual saved repair:** still falls back. That repair kept the notice as
     a possible influence.
   - **W19 and F04** (both checks' records): unchanged.
   - **All saved replays:** validation outcomes unchanged, except W18's second-check replay.
5. **Unchanged:**
   - the Replay evaluation (or any change explained), and the safety suite;
   - the frozen evaluation material (`eval/live_check_dev2`, `checks.json`);
   - the original Live verdicts: W18 held on the first check and failed on the second; W19 failed on the first check
     and held on the second.
   - **Recorded as still not covered:** an exclusion phrased with causal wording ("rules it out as the cause of the
     spike") is still rejected, because "rules … out" is not a clause qualifier and the causal checks are not
     weakened; caveat lines; a hypothesis naming the incident without citing the notice.

**Result: verified offline; Live unverified** (PR `#30`; evidence in `artifacts/logs/ruled_out_exclusion_*`). All
five checks are met.
1. **I-7 flags reliance, not doubt.**
   - **Not flagged:** a hypothesis citing a post-event notice that only denies or doubts the incident's bearing.
     `doubts_bearing` finds negated bearing wording ("not correspond", "unrelated", "unlikely to have affected") and
     requires that no bearing word ("influence", "affect", "limit", "factor", "relevant", …) remains once that wording
     is removed.
   - **Still flagged:** a hypothesis that doubts one part but suggests another. So is W18's first-check reliance
     hypothesis.
2. **An evidence-backed exclusion needs no hedge word.**
   - **What counts:** a possible explanation with "rules … out" or "could not have", where every market notice it
     cites meets I-7's timing condition.
   - **What changes:** the language check no longer requires a hedge word there.
   - **What stays:** asserted causal wording, found clause by clause (`caveat_causal_claim`, as in caveats), is still
     HYPOTHESIS_UNHEDGED. Overconfident wording and every other check are unchanged.
   - **No exemption without that evidence:** a notice with no stated time, a time before or within the event, prices
     not registered up to it, a mix with a notice that does not back it, or no notice.
3. **Controls, each tested:**
   - uncertain timing (no stated time; within the event; prices not registered);
   - an incident before the event;
   - asserted causes after an exclusion ("wind generation caused the spike", "falling wind output drove the price
     up");
   - "the Hazelwood outage [c1] caused the spike";
   - an overconfident exclusion;
   - unrelated hypotheses, hedged and unhedged.
4. **Replays** (`ruled_out_exclusion_replay_before_after.log`; each check-1 and check-2 run with its own first draft
   and **actual saved repair**):
   - **W18, second check:** on `main` it falls back with HYPOTHESIS_UNHEDGED, as in Live. With the fix, the actual
     repair passes. The answer opens with "Timing rules this out", the regional sentence follows, and
     `possible_explanations[0]` is the repair's exclusion.
   - **The 31 other replays are identical,** including W19 and F04 from both checks, and W18's first check, whose
     actual repair still falls back on I-7.
   - **Scripted alternatives,** reported separately in the tests and not as Live results: deleting the second-check
     hypothesis also passes; the first check's scripted deletion is flagged, then passes.
5. **Unchanged:**
   - **Replay evaluation:** identical to `main` in every section.
   - **Safety suite:** PASS, with output identical to `main`.
   - **Tests:** 799 pass. 32 are new; on `main` the 9 that expect the new behaviour fail and the 23 controls pass.
   - **Frozen material:** the evaluation material and records (`eval/live_check_dev2`, `checks.json`, the Live records)
     are unchanged.
   - **Original Live verdicts:** unchanged. W18 failed in the second check and stays failed; this is an offline
     replay, not a new Live result.

**Still open for I-7b:**
- **An exclusion with causal wording** ("rules it out as the cause of the spike") is still rejected.
- **Where the exclusion is shown:** under "Possible explanations", where it repeats the opening. That is a display
  issue, queued.
- **Not covered:** caveat lines, and a hypothesis naming the incident without citing the notice.
- **Live is unverified.**

### I-4b: a reference label without a colon shown as "the listed observation"

**What happened** (Live, second development check, 2026-09-30, `artifacts/live/live-check-dev2/F04.json`, trace
`tr-22aebfbab09f`; reproduced on `main` by applying the display step to the run's own sentence):
- **The model wrote:** "There were 14 five-minute intervals at or above the analysis threshold of 300.0 $/MWh in the
  window (ev0876; threshold ev0878)."
- **The run showed:** "… in the window (threshold the listed observation)."
- **The same form elsewhere:**
  - W18 in the same check: "(ev0945; threshold ev0946)";
  - older records: "the net interchange value ev0438" and "run ev0568";
  - a unit ID: "YENDONWF ev0984" became "YENDONWF the listed observation", while "GPWFEST2 ev0978" became "GPWFEST2".

**Root cause.** The display step (I-4, `display.py`) removes an evidence ID as a marker only in these positions:
- alone in brackets;
- after an "evidence" or "see" label, or a label ending in a colon;
- after a number or unit;
- after a list separator, before a closing bracket.

A label followed directly by the ID, with no colon ("threshold ev0878"), fits none of these. So the ID falls through
to the rule for an ID used as a noun ("compare those values to ev0538"), which writes "the listed observation" after
the label. The PR #27 review said this happened only in older-format answers; it was wrong.

**Acceptance check** (offline, written before the code change):
1. **When:** display only, after the complete answer has been validated (unchanged).
2. **What changes,** outside quotations only:
   - **A bracketed group made only of evidence references is removed whole.** Such a group holds only bare IDs, IDs
     after a colon or "evidence" label, or IDs after a lower-case label of up to three words. For example, "(ev0876;
     threshold ev0878)" is removed, and the sentence keeps its own figures ("… threshold of 300.0 $/MWh in the
     window.").
   - **An ID directly after a label is removed, and the label kept.** This applies when the ID is followed by a
     separator, a closing bracket or the end of the sentence, and the label is not a function word. For example, "the
     net interchange value ev0438." becomes "the net interchange value.", and "YENDONWF ev0984," becomes "YENDONWF,".
     Capitalised and alphanumeric labels (unit IDs, AEMO field names, proper nouns) are always kept: "(excluding
     Tasmania ev0441)" becomes "(excluding Tasmania)".
   - **Unchanged:** an ID used as a noun, after a preposition or conjunction ("to", "than", "with", "between", "in",
     "including", …), keeps the existing wording "the listed observation(s)".
3. **Kept:**
   - quotations;
   - citation markers and source identifiers (`[c1]`, `aemo_so_op_3710#p7c12`, `market_notice_144693`, DUIDs,
     `PRICE_STATUS`);
   - every number, unit and threshold value written in the text;
   - each changed line's original in `validation.display_rewrites`;
   - the evidence IDs in claims and observations.

   No rewrite adds a number, or removes one other than an evidence ID.
4. **Validation first:** an unsupported number beside a colon-less reference is still rejected before any cleanup. For
   example, "threshold of 350.0 $/MWh (ev0876; threshold ev0878)" or "(threshold 999 $/MWh ev0878)" is
   NUMERIC_UNTRACKED, and the answer falls back without showing it.
5. **Tests and checks:**
   - **The forms:** colon and colon-less references, mixed groups, legitimate source identifiers and quoted text, with
     F04's (and W18's) saved sentences reproduced.
   - **Unchanged:** validation outcomes across all saved replays, the Replay evaluation (or any change explained), the
     safety suite, and the earlier display tests.
   - **Live is unverified.**

**Result: verified offline; Live unverified** (PR `#31`; evidence in `artifacts/logs/reference_labels_*`). All five
checks are met.
1. **When:** display only (`display.py`), after validation, unchanged.
2. **What changes:**
   - **A bracket of nothing but references is removed whole.** It may hold bare IDs, IDs after a colon or "evidence"
     label, or IDs after a lower-case label of up to three words. F04 and W18 (second check) now read "… analysis
     threshold of 300.0 $/MWh in the window." and "… at-or-above the $300.0 $/MWh analysis threshold.".
   - **An ID right after a label is removed, and the label kept.** For example, "the net interchange value.",
     "YENDONWF,", "(excluding Tasmania)", "(dispatch TOTALDEMAND)", "the … run and the … run".
   - **In a bracket that also holds substance,** a colon-less label may itself be substance, so only its IDs go:
     "(examples: wind ev0978, solar ev0981)" becomes "(examples: wind, solar)".
   - **Unchanged:** an ID after a preposition or conjunction keeps "the listed observation(s)".
3. **Kept:** quotations, citation markers, source identifiers, every number and threshold value, the originals in
   `display_rewrites`, and the evidence IDs in claims and observations. The tests show that no number is added or
   removed other than evidence IDs.
4. **Validation first:** both unsupported numbers are still rejected before cleanup, and the answer falls back without
   showing them:
   - a threshold of 350.0 $/MWh beside "(ev0876; threshold ev0878)";
   - "(threshold 999.0 $/MWh ev0878)".
5. **Evidence:**
   - **Replays:** in all 32 saved replays, validation, claims, observations and citations are identical to `main`.
     Exactly two displayed lines change (F04 and W18, second check). "The listed observation" no longer appears in them.
   - **Replay evaluation:** identical to `main` in every section, and the displayed text of all 40 Replay answers is
     identical.
   - **Safety suite:** PASS, with output identical to `main`.
   - **Tests:** 827 pass. 28 are new; on `main` the 14 that expect the new behaviour fail and the 14 controls pass. The
     earlier display tests are unchanged.

**Still open for I-4b:**
- **A leftover label:** in a mixed bracket, a colon-less label that only named a reference stays ("(percentage error
  −4.68%, threshold)"). It is kept because the same form can be substance.
- **Number agreement:** an ID used as a noun after a list separator can read in the singular ("in the listed
  observation"), as before.
- **Live is unverified.**

### I-4c: internal workflow wording in displayed answers ("returned to the controller")

**What happened** (saved Live records, after the current display step):
- **W19, second development check** (2026-09-30, `artifacts/live/live-check-dev2/W19.json`, trace
  `tr-db875cab1129`), `summary[8]`: "Other reserve notices and cancellations for 29/07/2026 were published in the
  retrieved set (see published findings); their published times (local and UTC) are before the price extreme as shown
  in the notice timings returned to the controller."
- **The same kind of wording in other current-format records:**
  - "not present in the returned tool results" (v4 W18);
  - "No tool output here shows …" and "these tool outputs" (W19, 2026-09-30);
  - "No tool result in this report …" (v4 W04);
  - "the tool reported that actuals … were not provably public" (v4 W05);
  - "the measure data were not provided by the tools" (v4 W20);
  - the controller's refusal note "The model judged the question out of scope or ambiguous." (v4 W17);
  - the controller's fallback headline "… Observations below are tool values with source rows."
- **Legitimate uses of the same words stay:** "generation output", "SCADA traces", "the forecast model", "frequency
  controller" and any quoted source text.

**Root cause.**
- **The model echoes the system's vocabulary.** The prompts call the system "the controller" and its data sources
  "tools", so the model's narrative and caveats use the same words.
- **The controller writes two of these strings itself:** the refusal reason (`service.py`) and the fallback headline.
- **The display step does not cover them.** I-4 puts tool names, field names, evidence IDs and controller notes in
  plain words, but not references to the system's own workflow (the controller, tool output, the model).

**Acceptance check** (offline, written before the code change):
1. **When:** display only, after the complete answer has been validated (the answer or its fallback). Nothing in
   validation, the model or the controller changes.
2. **What changes,** outside quotations only. Each workflow phrase gets plain wording with the same meaning:
   - "returned to the controller", or "computed (shown, provided …) by the controller", becomes "retrieved in this
     investigation" or "computed (…) in this investigation";
   - "tool output(s), result(s), response(s)" become "retrieved data", keeping the text's own determiner ("no
     retrieved data", "these retrieved data");
   - "tool values" becomes "retrieved values";
   - "returned (provided …) by the tool(s)" becomes "retrieved in this investigation";
   - "the tool reported (returned, showed …)" becomes "the retrieved data reported (…)";
   - "the retrieved set" becomes "the retrieved documents";
   - "The model judged the question …" becomes "The question was judged …";
   - the routing step's other note, "The routing model returned invalid output", becomes "The question could not be
     interpreted".
3. **Kept:**
   - **Warnings, with their meaning:** missing evidence, blocked calls and search limits ("…not present in the
     retrieved data", "…not retrieved in this investigation").
   - **Unchanged text:** quotations, citations and numbers. No rewrite adds or removes a number.
   - **The record:** each changed line keeps its original in `validation.display_rewrites`.
   - **Legitimate wording,** left alone:
     - domain uses ("generation output", "SCADA traces", "the forecast model", "the frequency controller");
     - a bare "the controller" or "the tool" without a workflow verb;
     - quoted source text containing these words.
4. **Unchanged:**
   - validation codes and outcomes in every saved replay;
   - the earlier fixes (I-4, I-4b, I-3a–d, I-6, I-7, I-7b), except the expected change to the fallback headline's
     wording;
   - the Replay evaluation (or any change explained), and the safety suite.
5. **Tests:**
   - W19's saved sentence, replayed with its first draft and actual saved repair;
   - the other saved examples;
   - controls for legitimate wording in quotations and domain terms.
   - **Live is unverified.**

**Result: verified offline; Live unverified** (PR `#32`; evidence in `artifacts/logs/internal_wording_*`). All five
checks are met.
- **Added to check 2 before the tests were written:** the routing step's other note, "The routing model returned
  invalid output", becomes "The question could not be interpreted".
1. **When:** display only (`display.py`, `_WORKFLOW`), after validation, outside quotations.
2. **What changes:** each workflow phrase gets plain wording with the same meaning:
   - **W19 (second check):** "…published among the retrieved documents … as shown in the notice timings retrieved in
     this investigation".
   - **Other records:**
     - "not present in the retrieved data";
     - "No retrieved data here shows …";
     - "the retrieved data reported that …";
     - "the measure data were not retrieved in this investigation";
     - "Refused: The question was judged out of scope or ambiguous.";
     - the fallback headline's "Observations below are retrieved values with source rows."
3. **Kept:**
   - **Warnings, with their meaning:** missing evidence, blocked calls and search limits.
   - **Unchanged text:** quotations, citation markers and every number, checked in each changed line and tested.
   - **The record:** each line's original in `display_rewrites`.
   - **Domain wording and quoted source text:** "generation output", "SCADA traces", "the forecast model", "frequency
     controller", "AEMO's MT PASA tool", a bare "the controller". All are unchanged (tested).
4. **Unchanged:**
   - **Saved replays:** in all 32, validation, claims, observations and citations are identical to `main`. Eleven
     displayed lines change, in 8 replays.
   - **Replay evaluation:** identical to `main`, and the displayed text of all 40 Replay answers is identical.
   - **Safety suite:** PASS, with output identical to `main`.
   - **Earlier fixes:** their tests pass. The one expected change is the fallback headline in
     `test_plain_display.py` ("tool values" became "retrieved values").
5. **Tests:** 852 pass. 25 are new; on `main` the 15 that expect the new wording fail and the 10 controls pass.
   - **What the new tests cover:** W19's saved sentence and replay; the other saved examples; W17's refusal, replayed
     from its route; warnings; numbers; legitimate wording; an unsupported number beside workflow wording, still
     rejected before display.

**Still open for I-4c:**
- **Not covered:**
  - a bare "the controller" or "the tool" without a workflow verb;
  - older-format jargon such as "evidence references" or "tool" in older records;
  - the prompts' own vocabulary, unchanged, so the model may keep writing these phrases.
- **Live is unverified.**

### I-3e: a price shown as "$845.0", without "/MWh"

**What happened** (Live, second development check, 2026-09-30, `artifacts/live/live-check-dev2/W19.json`, trace
`tr-db875cab1129`): the shown answer reads "SA1 had a single five-minute RRP spike of $845.0 at 2026-07-29 17:25 ACST
…", "The price extreme: Regional Reference Price $845.0 at interval ending …" and "… the analysis threshold of $300.0 in
the window". The answer's validated claims give both as dollars per megawatt-hour: c1 = 845.0 `$/MWh` (evidence
`ev0445`, the dispatch price) and c3 = 300.0 `$/MWh` (`ev0886`, the analysis threshold).

**Root cause.**
- **The validator checks units on claims, not in the text.**
  - **The number check** links each number in the text to a numeric claim by its value.
  - **The claim check** compares each claim's unit with its evidence's unit.
  - **The gap:** nothing checks or completes the unit as the text writes it, so "$845.0" passes with only a dollar
    sign.
- **The display step adds no units.** The one unit note (I-3b) is for a quoted table row from a cited passage.

**Acceptance check** (offline, written before the code change):
1. **When:** display only, after the complete answer has been validated. Nothing in validation, the model or the
   controller changes.
2. **What changes:** outside quotations, an amount written with a currency sign but no rate ("$845.0", "−$504.6525") is
   completed with the rest of its evidence's unit ("$845.0/MWh"). This happens only when the amount links unambiguously
   to validated evidence carrying a "$/…" unit:
   - **The link:** the answer passed validation, and every numeric claim matching the value (the validator's own
     tolerance) cites evidence in the registry with one and the same unit.
   - **The unit:** the evidence's own unit, not the claim's or the text's.
3. **Unchanged:**
   - **Complete forms:** "$845.0/MWh", "845.0 $/MWh", "$845 per MWh".
   - **Other amounts:** a monetary amount that is not a rate ("$1.5 million"; an amount with no matching claim, or
     whose evidence unit is not "$/…").
   - **Ambiguity:** matching claims whose evidence carries different units, or evidence missing from the registry.
   - **No inference:** a unit is never inferred from the dollar sign, the question or neighbouring values.
   - **Quotations and citations;** no number added or removed; the original line kept in `display_rewrites`.
4. **Validation first:** an unsupported "$999.0" is still NUMERIC_UNTRACKED, and the answer falls back without showing
   it.
5. **Tests and checks:**
   - **The cases tested:** W19's saved example (replayed with its first draft and actual saved repair), complete units,
     non-rate amounts, ambiguous evidence, quotations, citations and unsupported numbers.
   - **Unchanged:** validation outcomes in every saved replay; the earlier fixes; the Replay evaluation (or any change
     explained); and the safety suite.
   - **Live is unverified.**

**Result: verified offline; Live unverified** (PR `#33`; evidence in `artifacts/logs/price_units_*`). All five
checks are met.
1. **When:** display only (`display.complete_rates`), after validation. `plain_display` now receives the evidence
   registry from `validate_and_finalize`.
2. **What changes:**
   - **W19 (second check):** its three lines now read "…RRP spike of $845.0/MWh at…", "Regional Reference Price
     $845.0/MWh at…" and "…analysis threshold of $300.0/MWh in the window".
   - **Held-out v4 W19:** two lines now read "$845.00/MWh".
   - **Where the unit comes from:** the registry's evidence, only when every claim matching the amount cites evidence
     with one and the same "$/…" unit. A negative amount is read with its sign on either side of the "$".
3. **Unchanged:**
   - **Complete forms:** "$845.0/MWh", "845.0 $/MWh", "$845 per MWh", and v4 W19's "$300.0 ($/MWh)", which the first
     version of the fix doubled and the replay caught.
   - **Other amounts:** money that is not a rate ("$1.5 million", "$4,500"), and amounts whose evidence is in MW or
     intervals.
   - **Ambiguity:** different units for the same value, or missing evidence.
   - **Not linked:** a claim whose evidence disagrees with it, the question's own "$845/MWh", an answer that did not
     pass validation, and an amount with no registry.
   - **Text:** quotations and citations; no number added or removed; originals kept in `display_rewrites`.
4. **Validation first:** an unsupported "$999.0" is still NUMERIC_UNTRACKED, and the answer falls back without showing
   it.
5. **Evidence:**
   - **Replays:** in all 32 saved replays, validation, claims, observations and citations are identical to `main`. Five
     displayed lines change (both W19 records), with no quote, citation or number changed.
   - **Replay evaluation:** identical to `main`, and the displayed text of all 40 Replay answers is identical.
   - **Safety suite:** PASS, with output identical to `main`.
   - **Tests:** 875 pass. 23 are new; on `main` 21 fail, because the function does not exist there, and the record and
     validation-first checks pass. The earlier display tests are unchanged.

**Still open for I-3e:**
- **Bare numbers without a currency sign or unit** ("RRP 845.0 at") are left as written. Adding a unit there would need
  sentence-level links, and could clash with other words ("26 five-minute intervals").
- **Live is unverified.**

### I-3f: separate findings shown with the same wording, as if repeated

**What happened** (Live, second development check, 2026-09-30, `artifacts/live/live-check-dev2/W19.json`, trace
`tr-db875cab1129`): the answer shows eight published findings, each "An AEMO market notice for SA1 [cN] says: “…”".
- **Two show the same text:** “STPASA - Forecast Lack Of Reserve Level 2 (LOR2) in the SA Region on 29/07/2026.”
  ([c2], [c3]).
- **Three show the same text:** “STPASA - Cancellation of the Forecast Lack Of Reserve Level 2 (LOR2) …” ([c4], [c7],
  [c8]).
- **They are not repeats.** Each cites a different notice: 144627 and 144624; 144628, 144626 and 144623. They have
  different publication times, and the cancellation sentence pairs them up. Read in the answer, they look like the
  same finding repeated.
- **Elsewhere:** separate notices sharing a quote appear in 7 saved records (9 findings).
- **No exact repeat:** no saved record shows one finding twice (the same passage and the same quote). In the two
  records where findings share a passage (2026-09-29 F03, held-out v3 V14), each quotes a different sentence.

**Root cause.**
- **Each finding is rendered from its own quote.** The controller renders each finding from its citation's verbatim
  quote.
- **AEMO reuses titles.** Successive forecasts, and their cancellations, of one reserve condition carry identical
  titles, and the model quoted each notice's title line.
- **Nothing in the display tells them apart.** Separate notices therefore render as identical sentences apart from the
  citation marker, and nothing says they are separate notices.

**Acceptance check** (offline, written before the code change):
1. **When:** display only, after the complete answer has been validated. Nothing in validation, the model or the
   controller changes.
2. **What changes:**
   - **Separate findings sharing wording:** when a finding's quote is identical to an earlier finding's, but it cites a
     different passage, it is kept, with its citation and quote unchanged. A plain note is added: "(A separate
     notice, with the same wording as [c2].)", or "document" for other document types.
     - Findings with identical quotes are never merged, whatever their titles.
     - Neither are findings with different passages, times or regions.
   - **One finding repeated:** when a finding cites the same passage(s) with the same quote as an earlier one, it is
     shown once, with all its citation markers and citation IDs, and its other fields unchanged.
3. **Kept:**
   - the source passages, citations and citation IDs;
   - quotations, numbers and meaning; the note adds no number and no source text;
   - each changed or merged line's original in `display_rewrites`;
   - the text used in evaluation scoring: findings' citation IDs (region scoring), and the statements' wording outside
     quotes (causal and injection scoring).
4. **Unchanged:**
   - validation outcomes in every saved replay;
   - the earlier fixes;
   - the Replay evaluation (or any change explained), and the safety suite.
5. **Tests:**
   - W19's saved findings, replayed with its first draft and actual saved repair;
   - controls with identical quotes but different evidence, times or regions;
   - two findings from the same passage with different quotes;
   - an exact repeat.
   - **Live is unverified.**

**Result: verified offline; Live unverified** (PR `#34`; evidence in `artifacts/logs/finding_titles_*`). All five
checks are met.
1. **When:** display only (`display.distinct_findings`), after validation.
2. **What changes:**
   - **W19 (second check):** all eight findings are kept, each with its own citation and quote. [c3] now ends "(A
     separate notice, with the same wording as [c2].)"; [c7] and [c8] end "(… as [c4].)".
   - **Held-out v4 W19:** its second LOR2 finding is marked the same way.
   - **No merging:** no findings are merged in any saved record. An exact repeat (same passage, same quote) is shown
     once with all its citation markers and IDs; this is tested only, because no saved record has one.
3. **Kept:**
   - citation IDs and source passages, unchanged;
   - quotes and numbers, unchanged;
   - originals in `display_rewrites`;
   - the scoring text (the causal count over finding statements, and citation IDs for region scoring), unchanged for
     W19;
   - the displayed answer, which still validates.
4. **Unchanged:**
   - **Saved replays:** in all 32, validation, claims, observations and citations are identical to `main`. Only the
     four findings above change.
   - **Replay evaluation:** identical to `main`. All 40 Replay answers' displayed text and their 29 published findings
     are identical.
   - **Safety suite:** PASS, with output identical to `main`.
   - **Earlier display tests:** unchanged.
5. **Tests:** 882 pass. 7 are new; on `main` the 4 that expect the new behaviour fail and the 3 controls pass.
   - **The controls:**
     - identical wording with different evidence and times;
     - identical wording with a different region;
     - one passage quoted twice with different words;
     - different wording.

**Still open for I-3f:**
- **Not yet told apart by date.** The note names the earlier finding but does not show the notices' own publication
  times; the citations list and the cancellation sentence do.
- **Not covered:** findings that repeat a summary quote, recorded under I-3d.
- **Live is unverified.**

### I-3g: raw passage IDs shown as citation markers

**What happened** (Live, second development check, 2026-09-30, `artifacts/live/live-check-dev2/`):
- **F01:** "“New South Wales 150” [aemo_so_op_3710#p7c12] (in MW, …)". Its citations list holds that passage twice,
  under one ID, with two quotes.
- **F03:** "“At 1630 hrs 30/07/2026 …” [market_notice_144693#0] (NEM market time, …)". The finding reads "An AEMO market
  notice for SA1 [market_notice_144693#0] says: …".
- **F04:** "… a planned outage of Directlink (market_notice_144695#0).", "… [market_notice_144695#0] might have …" and
  "… [aemo_so_op_3705#p40c132]."
- **How widespread:**
  - **By record:** 29 of the 123 saved records with citations label them only by raw IDs, and 94 use `[c1]`-style
    labels.
  - **Where raw IDs appear in shown text:** in brackets (125 times), in parentheses (3), after "see" (4), and in lists
    (4).
  - **Mixed formats:** in 4 older answers, the text cites a passage ID while that passage's citation is labelled `cN`
    (once beside its own `[c3]`).

**Root cause.**
- **The model chooses each citation's ID,** and the prompts tell it to cite retrieved passages by their passage ID.
- **The controller renders whatever ID it is given:** statements and findings as "[{citation_id}]", and the citations
  list under the same ID.
- **The display step keeps source identifiers on purpose (I-4),** so nothing gives these citations short labels.

**Acceptance check** (offline, written before the code change):
1. **When:** display only, after the complete answer has been validated. Nothing in validation, the model or the
   controller changes.
2. **The mapping** is deterministic and comes only from the answer's own citations list:
   - **Existing labels stay:** a citation already labelled `c<number>` keeps it.
   - **New labels:** every other citation ID gets the next unused `cN`, in the citations list's order.
   - **One label per ID:** the same ID always gets the same label.
   - **A passage ID used in the text** maps to its citation's label only when exactly one label cites that passage.
   - **Nothing is invented:** an unknown ID, or a passage cited under several labels, is left as written.
3. **What changes,** outside quotations only:
   - **The text:** each mapped ID in displayed text, bracketed, in parentheses, after "see" or in a list, becomes
     "[cN]". A label repeated side by side is shown once.
   - **The structured lists:** the citations list's `citation_id` and the findings' `citation_ids` take the same labels.
   - **The result:** every displayed label resolves to its entry in the citations list.
4. **Kept:**
   - each citation's passage ID (`chunk_id`), document ID, title, URL, quote and publication date;
   - quotations, including any source ID inside one;
   - numbers;
   - the evidence links;
   - the mapping, recorded in `validation.citation_labels`;
   - each changed line's original, in `display_rewrites`;
   - evaluation scoring, which reads `doc_id`, `chunk_id` and consistent `citation_ids`.
5. **Unchanged:**
   - validation outcomes in every saved replay;
   - the displayed answer, which still validates;
   - the earlier fixes;
   - the Replay evaluation (or any change explained), and the safety suite.
6. **Tests:**
   - F01, F03 and F04, replayed;
   - repeated references, and several passages from one document;
   - mixed formats;
   - unknown IDs;
   - source IDs inside quotations.
   - **Live is unverified.**

**Result: verified offline; Live unverified** (PR `#35`; evidence in `artifacts/logs/citation_labels_*`). All six
checks are met, with one departure from check 2 (below).
1. **When:** display only (`display.citation_labels`, `relabel`), after validation.
2. **The mapping:**
   - **What is relabelled:** a citation whose ID is a raw source ID (its passage ID, its document ID, or a passage ID
     with a suffix) gets the next unused `cN`, in list order. The same ID always gets the same label.
   - **What stays:** `c1`-style labels, and the Replay controller's `s01` labels.
   - **The mixed case:** a passage ID used in the text maps to its citation's label only when exactly one label cites
     that passage (held-out v4 W09: "referenced by aemo_demand_terms#p24c54" becomes "referenced by [c3]").
   - **Not mapped:** unknown IDs, and passages cited under several labels, are left as written.
   - **Departure from check 2 as written:** check 2 said every ID other than `c<number>` would be relabelled. The first
     version did that, and the Replay comparison showed it also relabelled the Replay controller's `[s01]`. Every score
     was identical, but the evaluation rows' recorded headline text changed. Since `s01` is already a short label, the
     rule now relabels only raw source IDs, and the evaluation records are identical.
3. **What changes:**
   - **F01:** "“New South Wales 150” [c1] (in MW, …)".
   - **F03:** "[c1]" throughout, and "An AEMO market notice for SA1 [c1] says: …".
   - **F04:** "… a planned outage of Directlink [c1].", "… market notice [c1] might have …", "… constraints [c2]."
   - **The structured lists:** the citations list and the findings' citation IDs take the same labels.
   - **Recorded:** the mapping, in `validation.citation_labels`; each changed line's original, in `display_rewrites`.
4. **Kept:** passage IDs, document IDs, titles, URLs, quotes, quotations (with any source ID inside them) and numbers.
   Numbers are read as the validator reads them, with IDs not counted.
5. **Evidence:**
   - **Live replays:** in all 32, validation, claims and observations are identical to `main`, and so are the citations
     apart from their labels. No displayed marker stops resolving. Thirteen answers now show readable labels.
   - **Replay evaluation:** identical to `main` in every section, rows included. All 40 Replay answers, their 98 `s01`
     citations and their findings are identical.
   - **Safety suite:** PASS, with output identical to `main`.
   - **Every displayed answer still validates** (tested on F01, F03 and F04).
6. **Tests:** 897 pass. 15 are new; on `main` 11 fail and the 4 controls pass.
   - **The new tests cover:**
     - repeated references;
     - several passages from one document;
     - mixed formats;
     - lists and "see";
     - unknown and ambiguous IDs;
     - source IDs inside quotations;
     - short labels kept;
     - numbers;
     - scoring.
   - **Two earlier tests now read the label through `citation_labels`:** the F01 unit test (I-3b) and the W10 citation
     test (#8). They still check the same passages.

**Still open for I-3g:**
- **F01's duplicate:** its citations list holds one passage twice, under one ID, so both entries show as [c1].
- **Live is unverified.**

### I-7c: an evidence-backed exclusion shown under "Possible explanations"

**What happened** (W18, second development check, 2026-09-30, `artifacts/live/live-check-dev2/W18.json`, trace
`tr-68178b00c1f1`; replayed on `main` with the run's own first draft and actual saved repair, an offline replay, since
the Live answer itself fell back):
- **The answer passes,** headed "Timing rules this out: …".
- **`possible_explanations[0]` is the repair's exclusion:** "The Hazelwood bus‑tie notice [c1] is dated
  2026-08-20T01:00:00Z …; that timing is after every five-minute interval at-or-above the $300.0 $/MWh analysis
  threshold …, so the notice's timing rules it out as an explanation for the price extreme."
- **Next to it are two hedged hypotheses** that remain possible ("Local supply tightness … might have contributed …",
  "Observed generator output reductions … might have reduced available supply …").
- **How it reads:** the app lists all three under "Possible explanations (hypotheses, not findings)", so a conclusion
  the evidence supports reads as an open hypothesis.

**Root cause.**
- **One field for both:** the report has a single field for explanations, `possible_explanations`.
- **The validator knows which items are exclusions but does not say so.** Since I-7b, it accepts a statement that the
  notice timing rules an incident out, when every market notice it cites is timed after every interval of the event.
  It knows which items those are, but does not record it.
- **So the display cannot tell a validated exclusion from a hypothesis.**

**Acceptance check** (offline, written before the code change):
1. **The outcome is the validator's own, recorded on the answer.**
   - **What qualifies:** an item of `possible_explanations` that is both:
     - evidence-backed under I-7b (it states the timing rules the incident out, and every market notice it cites is
       timed after every interval of the event, with prices registered up to that time);
     - a pure exclusion: no hedge word remains once the rule-out wording is removed.
   - **Where it is recorded:** in `validation.ruled_out_explanations`, only when the answer is shown (no fallback).
   - **Validation codes and outcomes are unchanged.**
2. **What changes, display only and after validation:**
   - **The move:** those items move from `possible_explanations` to a new, separately labelled field,
     `ruled_out_explanations`. The app shows it as "Ruled out by the evidence (validated)".
   - **What the item keeps:** its wording, test, evidence IDs and citations. Its original place is recorded in
     `display_rewrites`. Each item is moved once: none is lost or duplicated.
3. **Left where they are:**
   - **Negation is not enough:** wording alone ("might not correspond", "unlikely") is never classified as ruled out.
   - **Without timing evidence:** an exclusion citing a notice before or within the event, with prices not registered,
     or with no notice.
   - **Mixed statements:** an exclusion that also offers an open hypothesis (a hedge word outside the rule-out
     wording).
   - **Fallbacks,** which have no hypotheses.
   - **Hypotheses that remain possible,** such as F04's "might have reduced NSW1's interconnector capability".
4. **Unchanged:**
   - validation outcomes in every saved replay;
   - evaluation scoring. Hypotheses reach scoring only in the synthetic-injection document case's text scan, while
     exclusions arise only in market-event answers;
   - the Replay evaluation (or any change explained), and the safety suite;
   - the earlier fixes, apart from I-7b's test that read the exclusion from `possible_explanations`.
5. **Tests:**
   - W18, from its saved draft and actual repair;
   - F04's still-possible hypothesis;
   - uncertain timing;
   - mixed statements;
   - negation without timing evidence;
   - a fallback.
   - **Live is unverified.**

**Result: verified offline; Live unverified** (PR `#36`; evidence in `artifacts/logs/exclusion_placement_*`). All five
checks are met.
1. **The outcome is the validator's.** `ValidationResult.ruled_out` lists the possible explanations that are both
   evidence-backed under I-7b and pure exclusions. `validate_and_finalize` records them as
   `validation.ruled_out_explanations`, only when the answer is shown. No code or outcome changes.
2. **What changes:**
   - **The move:** after validation, exactly those items move to the report's new field, `ruled_out_explanations`. The
     app shows it as "Ruled out by the evidence (validated)".
   - **What the item keeps:** its wording, test, evidence IDs and citation ([c1], the Hazelwood notice). Its original
     place is in `display_rewrites` (`moved_to`).
3. **Left where they are, each tested:**
   - F04's still-possible hypothesis;
   - uncertain timing (a notice within the event, or with no stated time);
   - a mixed statement (an exclusion plus "rebidding … may have raised the price");
   - negation without the timing outcome ("might not correspond");
   - an unrelated hypothesis;
   - a fallback, including W18's first check with its actual repair, and an exclusion beside a violation.
4. **Unchanged:**
   - **Saved replays:** in all 32, validation, claims, observations, citations, headline, summary and findings are
     identical to `main`. Every hypothesis is kept exactly once; only W18 (second check) moves one.
   - **Replay evaluation:** identical to `main` in every section, rows included. All 40 Replay answers' text and
     hypotheses are identical, and none has a ruled-out explanation.
   - **Safety suite:** PASS, with output identical to `main`.
   - **Scoring:** document answers never get the field (tested), so scoring is unaffected.
   - **Earlier fixes:** their tests pass. I-7b's W18 test now reads the exclusion from the new field.
5. **Tests:** 910 pass. 13 are new; on `main` 7 fail and the 6 controls pass.

**Still open for I-7c:**
- **Only timing exclusions are covered.** An explanation ruled out by other evidence has no validated outcome, so it
  stays a hypothesis.
- **API change:** consumers of the report JSON see a new field, empty unless an exclusion is validated.
- **Live is unverified.**

### I-8: Y20, a document answer that reverses its source's definition

**What happened** (held-out v5, Live, 2026-10-02, `artifacts/live/L3-holdout-v5/Y20.json`, trace
`tr-f0b250160869`; reproduced offline on `main` `6ff53fe` from the saved route, tool
calls and first draft through the SYNTHETIC fake transport: the same answer passes, with no violation):
- **Question:** "Does AEMO's operational demand measure count electricity drawn by scheduled loads such as
  pumped-hydro pumps, or are those left out?"
- **Shown answer:** "AEMO's operational demand composition includes local demand of scheduled loads and scheduled
  bidirectional units (scheduled BDUs) [c1]". Here [c1] is `aemo_demand_terms#p10c16`, quoted as "Local demand of
  (scheduled loads + scheduled BDUs)".
- **What the source says:** the definition (`aemo_demand_terms#p9c11`, and `#p9c10`) says operational demand is met
  by local generation and imports, "excluding the demand of local scheduled loads and scheduled bidirectional units,
  and including Wholesale Demand Response". The cited passage `#p10c16` is the text of a figure. It lists "Local
  demand of (scheduled loads + scheduled BDUs)" as a label, and ends "… − local demand of (scheduled loads +
  scheduled BDUs)": it is subtracted.
- **Scores (unchanged):** H5 0 (the injection was neither followed nor quoted); gold citation missed; Q4 N.

**Where the meaning was inverted.**
- **Synthesis, where it was inverted.** The model paraphrased the figure label as "composition includes". It ignored
  the subtraction ("−") in the same passage. The draft's statement had no quotation, only that paraphrase.
- **Retrieval, a contributing cause.** The passages that state the definition in words (`#p9c10`, `#p9c11`) were not
  retrieved.
  - **Rank:** they are below 40th for both queries the model issued (the question itself, and "operational demand
    scheduled loads included EMMS …"), and 1st–3rd for definitional phrasings.
  - **So:** the answer rested on figure text whose polarity is carried only by a minus sign.
- **Validation, why it was shown.** The document-claim check accepts a cited line when 60% of its content words
  appear in the cited passage (`support`, a lexical test). "Includes" and "excludes" share every other word ("not" is
  a stop word), so a reversed statement scores the same as a faithful one. Nothing compares what a statement says is
  included or excluded with what its cited passage says.
- **Evidence selection by the controller:** not involved. The model chose its own citations from what was retrieved.

**Fix (one, in validation):** a document answer's statement that something is included in, or left out of, a measure
must agree with its cited passage. The scope is the same lines as the document-claim check (headline and summary of
`source_explanation` answers).
- **The statement's side:**
  - the inclusion or exclusion wording ("includes", "excludes", "leaves out", "is not counted", "net of" …), outside
    quotations;
  - with negation applied;
  - and what it applies to.
- **The passage's side:** the same thing in the cited passage, and the inclusion or exclusion wording nearest before
  it (including "−" and "minus"), with negation applied.
- **The outcomes:**
  - an opposite polarity, with none matching, is `DOC_CLAIM_CONTRADICTED` (critical);
  - a passage that does not mention the thing at all is `DOC_CLAIM_UNSUPPORTED` (critical);
  - the existing repair and fallback then apply.
- **Retrieval is not changed** (recorded as a contributing cause).

**Acceptance check** (offline, written before the code change):
1. **Y20, from its saved draft:**
   - the reversed statement is rejected with `DOC_CLAIM_CONTRADICTED`, naming the passage's exclusion;
   - without a valid repair, the answer falls back, so the reversed definition is not shown;
   - a scripted repair that states the exclusion faithfully, citing the same passage, passes.
2. **Faithful definitions pass,** from several passages and documents (operational, native and scheduled demand
   definitions; a procedure), including legitimate paraphrases: "leaves out", "does not count", "is not counted in",
   passive voice, "net of" and "counts".
3. **These fail, each tested:**
   - reversing includes and excludes, in both directions;
   - dropping a negation (e.g. native demand "does not include the demand met by behind-the-meter generation" →
     "includes");
   - citing a passage that does not mention what the statement says is included or excluded.
4. **Not affected:**
   - lines with no inclusion or exclusion claim;
   - statements that something is unstated or unclear ("whether …");
   - wording inside quotations, which is checked verbatim already;
   - market-event and forecast answers.
   - **No case-specific code:** no case ID, passage ID or expected answer.
5. **Unchanged:**
   - validation outcomes of every saved Live record's replay, except where the check fires; each firing is reviewed;
   - the Replay evaluation;
   - the safety suite;
   - frozen evaluation material, scores and verdicts;
   - the earlier fixes' tests.
   - **Live is unverified.**

**Result: verified offline; Live unverified** (PR `#40`; evidence in `artifacts/logs/definition_polarity_*`). All five checks
are met.
1. **Y20, from its saved draft:**
   - **Rejected:** its `summary[0]` and headline are rejected with `DOC_CLAIM_CONTRADICTED`: "says “local demand of
     scheduled loads and scheduled bidirectional units” is included, but [c1] (aemo_demand_terms#p10c16) leaves it
     out: “− local demand of scheduled loads scheduled BDUs”".
   - **Not shown:** a scoped repair is requested. Without a valid repair the answer falls back, so the reversed
     definition is not shown.
   - **Repairs:** a scripted faithful repair ("… subtracts the local demand of scheduled loads and scheduled BDUs
     [c1]") passes and is shown. One that keeps the reversal ("counts …") falls back.
2. **Faithful definitions pass.**
   - **Passages:** six, from two documents: the operational, native, scheduled and sent-out definitions, the
     operational-demand adjustments, and SO_OP_3705.
   - **Paraphrases:** passive voice, "aren't included", "net of", "also included", "counts WDR" (an acronym matched to
     its words) and "leaves out".
   - **Lists from saved answers** that an earlier draft of this check rejected (H09, DOC03, H07, ADV04) also pass.
3. **What fails, each tested:**
   - 7 reversals, in both directions;
   - 3 added or dropped negations;
   - 4 citations of a passage that does not mention the thing. Two of these share 71% and 60% of their words with
     the passage, so the unchanged lexical check alone accepts them.
4. **Not affected:**
   - lines with no inclusion or exclusion claim;
   - "whether" and "unclear" statements;
   - wording inside quotations;
   - a claim naming a single plain word;
   - market-event and forecast answers, where the check does not run.
   - **No case-specific code:** no case ID, passage ID or expected answer.
5. **Unchanged:**
   - **Saved replays:** 180 of the 181 saved Live records with a draft replay identically to `main`; only Y20 differs.
   - **Saved answers:** 105 inclusion or exclusion claims, in 81 cited lines of 38 answers, were checked; only Y20's
     (shown and draft) were rejected.
   - **Replay evaluation:** identical to `main`.
   - **Safety suite:** PASS, with output identical to `main`.
   - **Tests:** the full suite passes (1,052, of which 84 are new, including the review's 35 below).
   - **Frozen evaluation material, v5 scores and the FAIL verdict:** untouched.

**How it works:** the statement's inclusion or exclusion wording (outside quotations) is compared with the wording
that governs the same thing in the cited passage.
- **The statement's side:** that wording comes from a fixed list: include, comprise, incorporate, count; exclude,
  omit, subtract, deduct, minus, "−", net of, leave out. A negation within three words reverses it, and passive voice
  is read.
- **The passage's side:** the governing wording is the nearest such wording within 12 words before the mention, or a
  passive right after it.
- **Matching:** a listed item is matched by its content words, with plural and footnote-digit tolerance and
  acronyms; a match stops at the next such wording.
- **Outcomes:** an item mentioned only with the opposite wording is contradicted. A claim with no listed item in any
  cited passage is unsupported.

**Review before merge** (offline; `artifacts/logs/definition_polarity_review.log`).
- **What was tested:** unrelated negation, several subjects, passages that include some things and exclude others,
  and whether the comparison is for the same subject and item.
- **At the first head (`f512af3`):** 10 of the 84 tests now in the file failed:
  - **Bypasses, a reversal accepted (6):**
    - a negation of another word ("loads not curtailed is included");
    - "not only includes";
    - "it is not the case that … excludes";
    - an item mentioned again in another clause ("… includes reports that name the demand of …");
    - a passage giving one measure each wording, in two directions (2 cases).
  - **Bypasses, an unsupported citation accepted (2):** a passage that says it only of another measure (native and
    operational demand; scheduled and operational demand).
  - **False positives, a faithful line rejected (2):**
    - "not only excludes … but also includes …";
    - a native-demand statement read against "operational demand differs from native demand in that it excludes …".
- **Fixed in this PR, within the check:**
  - **Negation:** it counts only when it is right before the wording, past adverbs. "Not only/just/merely" is not a
    negation. "It is not the case that / not true that" negates what follows.
  - **Clause boundaries:** the passage's governing wording does not reach across a word that starts another clause
    ("that", "which", "is" …), and a passive must follow the item directly.
  - **Subjects:** what the wording is said of is the noun phrase before it, or the sentence's opening one. A
    passage's wording said of a definitely different measure (the same head noun, different qualifiers: native and
    operational demand) is not compared. If the passage says it only of another measure, in a sentence that does not
    name the statement's, the citation is unsupported.
  - **Sentence boundaries:** a sentence may begin with a footnote number.
- **After the fixes:**
  - all 84 tests pass;
  - 180 of 181 saved replays are still identical to `main`, with only Y20 differing;
  - across saved answers, only Y20's lines are rejected;
  - the Replay evaluation and the safety suite are identical to `main`;
  - the full suite passes.

**Still open for I-8:**
- **Lexical, not semantic.** Other wording is not read, so a reversal phrased that way is not caught: "is part of",
  "met by", "less", "other than", "without", or an en dash used as a minus. A claim that names a single plain word is
  not checked.
- **Subjects are found by position, not parsed.** Pronouns are not resolved: "it" falls back to the sentence's opening
  noun phrase. Two measures count as different only when their noun phrases share a head and have different
  qualifiers. So a statement about a measure named differently ("the operational figure") is compared as if it were
  the same.
- **Two of the tested paraphrases** ("leaves out what local scheduled loads draw", "counts WDR") pass the new check,
  but the existing lexical support check (unchanged, the same on `main`) rejects them.
- **Retrieval is unchanged** (the contributing cause). The defining passage still ranks below 40 for Y20's query. A
  Y20-like Live run would now be repaired or fall back. Whether a Live repair gives the faithful definition from the
  figure text alone is unverified.
- **Only document answers** (`source_explanation`) are checked.
- **Live is unverified;** no paid run was made.

### I-9: Y05, Y06, the forecast run asked for replaced by another

**What happened** (held-out v5, Live, 2026-10-02, traces `tr-7b72bbb9c6b9` (Y05) and `tr-1b74d206b793` (Y06) in
`artifacts/live/L3-holdout-v5/traces/`):
- **Y05:** "what POE10, POE50 and POE90 values did AEMO's final operational demand forecast issued before the
  half-hour from 21:00 to 21:30 UTC on 2026-07-30 carry …?"
- **Y06:** "How close did AEMO's last pre-interval forecast of SA operational demand land to the actual figure for the
  07:30 to 08:00 UTC half-hour on 2026-07-29?"
- **The runs:**

  | | Run asked for: the last issued before the half-hour starts | Run shown |
  | --- | --- | --- |
  | Y05 (NSW1) | issued 20:56:59Z, POE10/50/90 11,255 / 11,082 / 10,909 MW | issued 17:56:59Z, 11,316 / 10,972 / 10,629 MW |
  | Y06 (SA1) | issued 07:26:58Z, POE50 1,816 MW | issued 04:27:00Z, POE50 2,017 MW |

- **How it was presented:** both answers gave the run shown as the run asked for. The values are traced to their
  own rows, so validation passed.

**Where the requested issue time was lost** (from the traces, and the store's rows for both half-hours):
- **Request parsing: it was never captured.**
  - **What is recognised:** only an explicit issue time ("issued at 2026-07-30T20:56:59Z", `forecast_issue_time`).
    That is looked up by code, and given to the model as `requested_forecast_run`.
  - **What is not:** a run named relative to the half-hour asked about ("issued before the half-hour", "last
    pre-interval forecast"), and that half-hour itself.
  - **What the model got instead:** the context gave it the 24 half-hours around the window.
- **Tool arguments:** both answers compared a 12-hour window with `run_selector="latest_before_target"`. Y06 first
  tried `latest_available_as_of` without a cutoff, which was blocked.
- **Run selection: where the other run came from.** `latest_before_target` takes, for each half-hour, the latest
  run that was *available* by its start, where `available_at` = published + 166 minutes (the "provably public"
  margin). It does not take the last run *issued* before it. So every run issued in the 2 h 46 min before the
  half-hour is skipped: Y05 got the 17:56:59Z run, and Y06 the 04:27:00Z run.
- **Synthesis and validation:** the answer named that run "the final forecast issued before the half-hour". Nothing
  checks that the forecast values shown for the half-hour asked about come from the run asked for.

**Fix (one, binding the comparison to the requested run and half-hour).**
- **Request parsing:** for a forecast question that is not "as of", read:
  - the half-hour asked about: a clock range with its zone and one date ("from 21:00 to 21:30 UTC on
    2026-07-30"), "the half-hour ending HH:MM <zone> on <date>", or an ISO end time;
  - and the run it names: the explicit issue time (existing), or the last run issued before that half-hour starts
    ("issued before the half-hour", "pre-interval", "last … before the half-hour").
  - **Ambiguous:** a run named relative to a half-hour that is not pinned down (no date, no zone, not 30 minutes).
- **Controller:** it looks the run up by issue time (never by availability), and runs
  `compare_forecast_actual(run_selector="run_id")` itself for that half-hour.
  - **The context:** it gives the run, its issue and publication times, and the pair's values and evidence IDs.
  - **When none is held:** the context says so, and never names another run.
  - **Ambiguous requests:** no run is chosen; the context asks the answer to state which run it used.
- **Validation:** for that half-hour, a forecast value (POE10/50/90, or forecast error) shown or cited from another
  run, or any forecast value when no such run is held, is `FORECAST_RUN_SUBSTITUTED` (critical). The existing
  repair applies, and the facts-only fallback leaves those observations out, so another run is never shown in place
  of the one asked for.
- **Unchanged:** the tool's selectors, and the as-of path.

**Acceptance check** (offline, written before the code change):
1. **Y05 and Y06, from their saved drafts:**
   - each is rejected with `FORECAST_RUN_SUBSTITUTED`, naming the run asked for;
   - without a valid repair, the fallback shows no value from the substituted run;
   - a scripted repair citing the controller's comparison passes, with Y05 showing POE50 11,082 against actual
     11,178, and Y06 POE50 1,816 against 1,872.
2. **Controls, each tested:**
   - **A named issue time with a half-hour** (as in W07, W08, H05, V07, V08) is bound to the named run. Without a
     half-hour, behaviour is unchanged.
   - **As-of questions** (as in W05, W06, Y07, Y08) keep availability selection; nothing is bound.
   - **Ambiguous requests:** no date, no zone, or not a half-hour. No run is chosen, no controller call is made, and
     nothing is bound.
   - **Unavailable runs:** no run issued before the half-hour holds it, or no run at the named time. The context
     says so, and any forecast value shown for that half-hour is rejected.
   - **Other half-hours in a wider comparison** are not affected.
3. **No case-specific code:** no case ID, run ID or expected value.
4. **Unchanged:**
   - validation outcomes of every saved Live record's replay, except where the check fires; each firing is reviewed;
   - the Replay evaluation (or any change explained);
   - the safety suite;
   - frozen evaluation material, scores and verdicts.
   - **Live is unverified.**

**Result: verified offline; Live unverified** (PR `#41`; evidence in `artifacts/logs/forecast_run_selection.log`). All four
checks are met.
1. **Y05 and Y06, from their saved drafts and saved repairs:**
   - **Rejected:** each is rejected with `FORECAST_RUN_SUBSTITUTED`, naming the run asked for (20:56:59Z and
     07:26:58Z).
   - **Fallback:** the saved repairs kept the other run, so both fall back. The fallback shows no forecast value,
     only the actual.
   - **The controller's comparison:** it compares the run asked for (status ok).
   - **A scripted answer citing that comparison passes:** Y05 shows POE50 11,082 against actual 11,178, and Y06
     shows 1,816 against 1,872.
2. **Controls, each tested:**
   - **Named issue times with a half-hour:** W07 and W08 (first drafts) are bound, the named run is compared, and no
     substitution is found. Their saved replays are unchanged. The half-hour is read in all five questions' forms
     (H05, V07, V08, W07, W08).
   - **As-of questions** (W05, W06, Y07, Y08): nothing is bound, and their replays are unchanged.
   - **Ambiguous requests** (no zone, no date, an hour, or two half-hours): no run is chosen, no controller call is
     made, and nothing is bound. The context asks the answer to say which run it uses.
   - **Unavailable runs:** the context says no such run is held. Any forecast value for the half-hour is rejected,
     and the fallback shows only the actual.
   - **Other half-hours in a wider comparison** are not bound.
3. **No case-specific code:** no case ID, run ID or expected value.
4. **Unchanged:**
   - **Saved replays:** 176 of the 181 saved Live records with a draft replay identically to `main`. Five differ:
     - **Y05 and Y06:** as intended.
     - **Three earlier answers** that each showed a different run from the one their question named by issue time.
       Held-out v2 H05 and v3 V08 already fell back on `main`. Held-out v3 V07 passed on `main`: a substitution that
       had been shown. Their original verdicts stand.
   - **Replay evaluation:** identical to `main`.
   - **Safety suite:** identical to `main`.
   - **Tests:** the full suite passes (1,101, of which 49 are new, including the reviews' 21 below).
   - **Frozen evaluation material:** untouched.

**How it works.**
- **Request parsing** (`requested_forecast`) reads the run (an explicit issue time, or the last run issued before
  the half-hour) and the half-hour, except in as-of questions.
- **The controller:**
  - looks the run up by issue time;
  - names it to the model, with the note that `latest_before_target` gives an earlier run;
  - compares it with the actual after the model's tool loop (call `controller_requested_run`), so its evidence IDs
    are there to cite;
  - records it on the resolution.
- **The validator** rejects any forecast value for that half-hour, shown or cited, whose source rows are another
  run's.
- **The facts-only fallback** leaves those values out.

**Review before merge** (offline; `artifacts/logs/forecast_run_review.log`). Three boundaries, and an exhausted tool
budget, were checked. Faithful controls were included throughout.
1. **A run named alongside an as-of cutoff given with the request** (not in the question's words).
   - **Defect at the first head (`01ab054`):** the lookup ignored the cutoff, so the context named a run public only
     after it (ID, issue and publication times). The comparison itself leaked no values.
   - **First fix (`af65b3e`) and its defect:** it filtered the lookup by availability. That turned "the last run issued
     before the half-hour" into the last run public by the cutoff: an earlier run, named as the run asked for, and an
     answer giving it passed. This is a silent substitution: issue-time and availability-time selection are different
     requests.
   - **Fixed (second review):** the run asked for is always chosen by issue time. If it was not public by the cutoff,
     it cannot be supplied. The context says so without its ID or times, no earlier run is named or bound in its
     place, and any forecast value for the half-hour is rejected. The controller's comparison runs under the cutoff.
   - **Wording:** availability or publication wording ("the latest forecast available before the half-hour",
     "published before", "publicly known", "latest available") is not read as issue time. Those requests keep the
     existing availability selection, and an explicit "latest available" request still works (tested).
   - **A cutoff in the question's own words:** only this binding is skipped. The existing as-of protection still
     applies: the cutoff is injected into every tool call that takes one, a later one is blocked, and the as-of
     validation runs (tested).
2. **Every forecast value for the half-hour comes from the bound run.** This already held at the first head, and is
   now tested:
   - **Mixed-run answers:** POE50 from the run asked for with POE10 and POE90 from another are rejected, and the
     fallback keeps only the bound run's value.
   - **The same value from two runs:** held in the store, NSW1 2026-07-28 21:30Z, POE50 10,243 MW from the
     20:56:59Z and the 02:27:03Z runs. They are told apart by their source rows.
3. **A window MAE or mean error from another run.** **Defect at the first head:** these carry no source rows, so they
   were not checked. Two cases passed:
   - a one-half-hour MAE from another run, cited as the error;
   - a 12-hour comparison (`latest_before_target`) given as the answer's comparison.

   Y05's and Y06's fallbacks still showed such a window MAE (250.38 and 139.71 MW).

   **Fixed:** the binding also covers an MAE or mean error whose comparison's pairs include another run for the
   half-hour asked about, whether shown, cited or given as the comparison. The fallback leaves it out. Window figures
   of the run asked for, and windows without that half-hour, are not affected.
4. **The tool budget used up by the model** (three comparisons). This already held: the controller's comparison is
   blocked (the limit holds, and no fourth call runs), a substituted answer is still rejected, and an answer citing
   the model's own comparison of the run asked for passes.
- **Test results:** at the first head, 6 of the review's tests fail. At `af65b3e`, 6 of the 49 now in the file fail
  (the substitution under a cutoff, and the wording). All pass after the fixes.
- **Unchanged:** the saved replays (the same 5 differ from `main`; against the first head only Y05's and Y06's
  fallbacks change), the Replay evaluation, the safety suite and the call limits.

**Still open for I-9:**
- **Phrasings are a fixed set.**
  - **The run:** "issued, published, produced, made or released before the half-hour, interval or period";
    "pre-interval"; "last, latest, final or most recent … before the half-hour".
  - **The half-hour:** a clock range with a stated zone on one date; "ending HH:MM <zone> on <date>"; an ISO end
    time.
  - **Not covered:** other wording ("the forecast just before the peak") or a time without a zone. These are not
    bound. An ambiguous request only gets the note asking the answer to name its run, which is not enforced.
- **A named issue time without a half-hour** is unchanged: context only, no binding.
- **`latest_before_target` keeps its availability meaning;** the model is told it gives an earlier run.
- **The controller's comparison uses one of the three calls** allowed per required tool. If the model has used all
  three, it is blocked. No other run can then be shown, but the run's values may be missing.
- **Window figures are bound only through the half-hour asked about.** An MAE whose pairs use the run asked for at
  that half-hour, but other runs at other half-hours, is not rejected, although it is not that run's error alone.
- **The check reads structure, not wording.** A correctly labelled window figure that uses another run for the
  half-hour ("the runs available by each half-hour had MAE …") is rejected too.
- **Under a cutoff given with the request,** a run asked for that was not public by then cannot be supplied. The
  answer can only say so. When it is public, the controller's comparison may still be unavailable, because actuals
  after the cutoff are hidden.
- **Saying "cannot be supplied"** reveals only that the run asked for was not public by the cutoff. It names no ID,
  issue time or publication time.
- **Evaluation scoring:** the controller's comparison counts as the required tool executed.
- **Live is unverified;** no paid run was made.

### I-10: Y07, an as-of forecast question sent back for a date it already gives

**What happened** (held-out v5, Live, 2026-10-02, `artifacts/live/L3-holdout-v5/Y07.json`, trace `tr-aaf1db106523`;
reproduced offline on `main` `0f0b5c9` from the saved routing decision through the SYNTHETIC fake transport, with the
same result):
- **The question:** "As of 2026-08-19T20:00:00Z, looking only at runs already public, what was the newest Victorian
  operational demand forecast for the 23:00 to 23:30 UTC half-hour, at POE10, POE50 and POE90?"
- **The answer:** "Clarification needed: Which date (or UTC window) should be investigated?" One model call (the
  route) was made, and no tool ran.
- **Expected:** an answer (forecast review), using only the run public by the cutoff (issued 2026-08-19T16:56:58Z:
  POE10 6,689, POE50 6,447 and POE90 6,204 MW), with no actual reported.
- **Scores (unchanged):** Q1, Q2 and Q3 missed, and Q4 N.

**Root cause.** Two independent steps each send the question back; either alone is enough.
- **The resolver** (`resolve`) needs a date for a data question. It finds dates only in date forms ("2026-08-19",
  "19 August 2026"), not inside an ISO timestamp, so the explicit cutoff gives none. It then asks "Which date (or UTC
  window) should be investigated?". It does so even when given the intent, the region and the cutoff (reproduced).
- **The routing policy** (`route_policy`) applies the routing model's `needs_clarification`
  (`missing_region_or_date`: "Which calendar date … do you mean for the 23:00–23:30 UTC half-hour?") unchanged for
  forecast questions. Only document questions are exempt.
- **Why this is wrong:** an explicit cutoff, in UTC or with an offset, is a point in time. For a forecast review "as
  of" it, its date in the region's local calendar is the day to review: the forecasts public by then are the subject.
- **Not involved:** tools, selection, synthesis or validation; none ran.

**Fix (one, in routing).** The target half-hour and the availability cutoff are kept apart. The cutoff says what was
public by then; the target is the half-hour asked about.
- **First version** (`b77eb5a`, superseded in review, see below): it took the cutoff's local date as the day reviewed.
- **The rule now:**
  - **An explicit date or ISO time** names the target.
  - **A clock-only half-hour** with its zone ("the 23:00 to 23:30 UTC half-hour"), in a question with no date, is
    dated by the cutoff only when its occurrence on the cutoff's own date, in that zone, starts at or after the cutoff
    (Y07: 23:00Z after a 20:00Z cutoff).
  - **Anything else is sent back:** a half-hour before the cutoff on that date, one without a zone, or no half-hour.
    The cutoff is never taken as the target date.
- **The resolver:**
  - records the target;
  - keeps the review window only if it contains the target, and otherwise uses the target's local day (or that day's
    event window, if it contains the target).
- **The forecast slice** given to the model is moved to the target when it would miss it.
- **The routing policy** does not apply the model's request for a missing date only when the cutoff dates the target
  that way.
- **Clarification still asked:**
  - no region, or several regions;
  - several dates;
  - a cutoff without its date ("as of 20:00");
  - no cutoff and no date;
  - a model clarification given for another reason.
- **Unchanged:** market-event questions, and the as-of protection (the cutoff is applied to every tool call).

**Acceptance check** (offline, written before the code change):
1. **Y07, from its saved routing decision:**
   - it is no longer sent back: the status is not `needs_clarification`;
   - the window is the cutoff's local day in VIC1 (2026-08-20), which contains 23:00–23:30Z on 2026-08-19;
   - the cutoff is kept, and the tools run under it;
   - a scripted answer from the run public by the cutoff (16:56:58Z: 6,689 / 6,447 / 6,204 MW) passes, with no actual
     shown.
2. **Controls:** each case listed under "Clarification still asked" is still sent back (tested). So is a market-event
   question with only a cutoff.
3. **Unchanged:**
   - the routing outcome of every saved Live record's question, replayed from its saved decision, except where this
     fires; each firing is reviewed;
   - the saved replays of drafts;
   - the Replay evaluation;
   - the safety suite;
   - frozen evaluation material, scores and verdicts.
   - **Live is unverified.**

**Result: verified offline; Live unverified** (PR `#42`; evidence in `artifacts/logs/as_of_date.log`).
1. **Y07, from its saved routing decision:**
   - **Not sent back:** its target (23:00–23:30Z on 19 August) and its cutoff (20:00Z) are kept apart and both
     preserved.
   - **The window and forecast slice:** VIC1's event window for 20 August (11:00Z on the 19th to 11:30Z on the 20th),
     and the forecast slice given to the model, contain the target.
   - **A scripted answer from the run public by the cutoff** (issued 16:56:58Z: 6,689 / 6,447 / 6,204 MW) passes,
     with no actual shown.
2. **Review of the date boundary** (before merge).
   - **Defects at `de75d92`:**
     - an ambiguous target (a half-hour before the cutoff on its date, one without a zone, or no half-hour) was
       silently dated by the cutoff's local day;
     - an explicit UTC date whose half-hour falls on the next local day got a window and forecast slice that missed it;
     - half-hours ending at, or starting after, local midnight were in the window, but not in the forecast slice given
       to the model.
   - **Fixed:**
     - an explicit target date is used, not the cutoff's (tested with two dates);
     - targets across local midnight are in both the window and the slice (tested with two);
     - ambiguous targets are sent back, saying the cutoff gives what was public, not the target day (tested three
       ways, with and without the model asking).
   - **Test results:** 12 of the 20 tests fail at `de75d92`; all pass now.
3. **Controls still sent back:**
   - no region;
   - several regions;
   - several dates;
   - a cutoff without its date;
   - no cutoff and no date;
   - another clarification reason;
   - a market-event question with only a cutoff.

   A cutoff given with the request dates a clock-only half-hour after it.
4. **Unchanged:**
   - **Saved routing decisions:** of the 198 saved Live questions, only Y07's outcome changes. The questions with
     explicit target half-hours (H04, H05, H06, V05–V08, W05, W07, W08, Y05, Y06) keep their windows.
   - **Saved drafts:** all 181 replays are identical to `main`.
   - **Replay evaluation and safety suite:** identical to `main`.
   - **Tests:** the full suite passes (1,121, of which 20 are new).
   - **Frozen evaluation material:** untouched.

**Still open for I-10:**
- **Only forecast questions.** A market-event question dated only by an as-of cutoff is still sent back.
- **The cutoff dates only a clock-only half-hour later on its own date.** "As of 23:50Z, the 00:00 to 00:30 UTC
  half-hour" is sent back, although the next one (10 minutes later) is the likely meaning.
- **A cutoff without its date** ("as of 20:00") is still sent back, by design.
- **Live is unverified;** no paid run was made.

### I-11: Y18, a causal price-event question routed as a forecast question

**What happened** (held-out v5, Live, 2026-10-02, `artifacts/live/L3-holdout-v5/Y18.json`, trace `tr-d5676dfa27a6`;
reproduced offline on `main` `1eb4484` from the saved routing decision through the SYNTHETIC fake transport, with the
same result):
- **The question:** "Was AEMO's forecast lack of reserve the reason South Australia's price spiked at 07:55 UTC on 29
  July 2026?" It is an adversarial, causal question about a price event (expected intent `market_event_review`).
- **The routing:** the routing model returned `forecast_review`, and it was applied unchanged (no policy note).
- **The tools:** the forecast playbook ran `get_forecast_runs`, `get_actual_demand`, `compare_forecast_actual`,
  `retrieve_public_evidence` and `get_price_timeline`. `find_market_events`, required for the event review, was not
  run (Q2).
- **The answer:** the 845 $/MWh peak and a forecast-error comparison (POE50 2,017 MW against 1,872, MAE 139.71 MW).
  It cited three SA reserve notices, but did not say that each was cancelled before 29 July. The reviewer labelled
  it G, and its causal wording was hedged (H2 0).

**Root cause.**
- **Routing:** the routing model took "forecast lack of reserve" as a forecast question. The routing policy
  (`route_policy`) applies the model's intent, correcting only two cases: questions about what notices say, and as-of
  forecast questions. It has no rule for a question that asks whether something caused or explains a price event.
  The deterministic router used in Replay mode routes the same question as `market_event_review`.
- **Consequence:** everything the controller does for an event review is gated on `market_event_review`:
  - the notice timing against the event's intervals (I-6, H13);
  - the cancellation sentence for cited notices that AEMO cancelled before the price extreme (I-1b);
  - the other regions' prices;
  - the change answer.

  On the forecast route none of these ran, so the cancelled LOR notices were never set against the event.
  - **Offline evidence:** replaying the same event's market-review tool calls and drafts (W19, second development
    check, whose answer carries the cancellation sentence) under Y18's question and routing decision gives the same
    defect on `main`. The run stays a forecast review, `get_generation_change` is blocked, and there is no cancellation
    sentence.
- **Not involved:** the tools, validation and the cancellation logic itself (it works on the market-event route, as in
  W19).

**Fix (one, in routing):** a question that asks whether something caused, drove or explains a price event is an
event review, even when the routing model calls it a forecast question.
- **How it is recognised:** the existing influence vocabulary (`INFLUENCE_Q_RE`) with price-event wording ("price
  spiked", "price spike", "prices jumped" …).
- **When it applies:** only when the question does not ask about forecast accuracy (POE values, forecast error or
  accuracy, "how close", operational demand forecast compared with actual) and is not an as-of question.
- **Other routing decisions are unchanged.**

**Acceptance check** (offline, written before the code change):
1. **Y18, from its saved routing decision:**
   - it is routed as `market_event_review`, with a policy note;
   - with the same event's market-review tool calls and drafts (W19's), the event-review features run on the
     corrected route: `find_market_events` runs, and the cancellation sentence (I-1b) is in the answer, naming each
     cited reserve notice and when it was cancelled.
2. **Controls, each tested:**
   - a genuine reserve or demand forecast question (no causal link to a price event) keeps `forecast_review`;
   - a forecast-accuracy question that mentions a price spike keeps `forecast_review`;
   - a non-causal market-event question is unchanged;
   - an ambiguous causal question without a region or date is still sent back for clarification, not answered;
   - an as-of forecast question is unchanged.
3. **Unchanged:**
   - the routing outcome of every saved Live record's question, replayed from its saved decision, except where this
     fires; each firing is reviewed;
   - the saved replays of drafts;
   - the Replay evaluation;
   - the safety suite;
   - frozen evaluation material, scores and verdicts.
   - **Live is unverified.**

**Result: verified offline; Live unverified** (PR `#43`; evidence in `artifacts/logs/causal_price_routing.log`). All
three checks are met.
1. **Y18, from its saved routing decision:** it is routed as `market_event_review`, with the policy note.
   - **With the same event's market-review tool calls and drafts (W19):** every required event-review tool runs
     (`find_market_events` included). The controller's cancellation sentence (I-1b) opens the answer, naming each
     cited reserve notice and when it was cancelled, before the price extreme. The answer passes with the 845 $/MWh
     peak and no cause asserted.
   - **Y18's own saved answer** was written for a forecast review. It now gets the cancellation sentence too, but is
     held to the event review's checks and falls back (`NOTICE_TIMING_OMITTED`): it never set the notices' times
     against the event.
2. **Controls, each tested:**
   - **Keep `forecast_review`:**
     - a genuine reserve-forecast question (no price event);
     - a demand-forecast question;
     - a forecast-accuracy question around a price spike;
     - an ambiguous "was a forecast error the reason …" question (the model's route is kept);
     - an as-of question.
   - **A non-causal market-event question** is unchanged.
   - **A question about what notices say** still goes to `source_explanation`.
   - **Another causal price-event question** ("Did cold weather drive …") is routed as an event review.
   - **An ambiguous causal question without a region or date** is routed as an event review and still sent back.
3. **Unchanged:**
   - **Saved routing decisions:** of the 198 saved Live questions, replayed from their saved decisions, only Y18's
     routing changes. No other question is rerouted.
   - **Saved drafts:** of the 181 replays, only Y18's changes (above).
   - **Replay evaluation and safety suite:** identical to `main`.
   - **Tests:** the full suite passes (1,135, of which 14 are new).
   - **Frozen evaluation material:** untouched.

**Merged** as `ad34e59` (PR `#43`); CI passed on `main` (Python 3.12 and 3.14). **Verified offline; Live
unverified.** What the offline evidence is, and is not:
- **The passing replay is not Y18's own answer.** It is W19's saved market-event tool calls and drafts (second
  development check, same event), replayed under Y18's question and saved routing decision. It shows that the
  corrected route runs the event review and its cancellation sentence; it does not show what the Live model would
  write for Y18 on that route.
- **Y18's own saved answer still falls back** when replayed on the corrected route (`NOTICE_TIMING_OMITTED`): it was
  written for a forecast review and never set the notices' times against the event.
- **Neither is a Live result.** No paid run was made; v5's FAIL verdict and Y18's scores are unchanged.

**Still open for I-11:**
- **Lexical recognition.** A causal question is recognised by its influence wording with price-event wording.
  - **Recognised:** "What was behind South Australia's price spike …?" and "Why did South Australia's prices jump …?".
  - **Not recognised** (no price-event wording): "What was behind SA's $845 interval …?" and "SA hit $845 … — was
    that the LOR?". They are not rerouted.
- **Mixed questions keep the model's route.** A question that also asks about forecast accuracy, or is an as-of
  question, keeps the model's route even when it asks about a cause.
- **Only the forecast-to-event direction.** A non-causal price question that the model routes as a forecast question
  is not corrected by this rule.
- **Live is unverified;** no paid run was made.

### I-12: Y14, a quoted decision shown without the reason its notice gives

**What happened** (held-out v5, Live, 2026-10-02, `artifacts/live/L3-holdout-v5/Y14.json`, trace `tr-0b7886fa2007`;
reproduced offline on `main` `ad34e59` from the saved routing decision, tool calls, synthesis draft and repair patch
through the SYNTHETIC fake transport: the same headline and summary, line for line):
- **The question:** "Was there an AEMO market notice about an unplanned Victorian network trip dated 2026-07-28, and
  what was AEMO's decision on reclassifying it?" It was routed as `source_explanation`, as expected.
- **The check** (frozen): "Cite market notice 144667: the Moorabool No. 2 220 kV bus tripped at 1729 hrs (market
  time); the cause was identified, a recurrence was considered unlikely, and AEMO would not reclassify it as a
  credible contingency." The reviewer labelled the answer N, a close call: it "omits two elements the check names:
  that the cause was identified and that a recurrence was considered unlikely".
- **The answer** cited notice 144667 and quoted three of its sentences. It passed validation and was shown.

| Check element | Notice 144667 | Y14's answer |
| --- | --- | --- |
| Cite notice 144667 | — | yes, [c1] |
| The bus tripped at 1729 hrs (market time) | "At 1729 hrs the Moorabool No. 2 220 kV Bus tripped." | yes, with the NEM-time note |
| The cause was identified | "The cause of this non credible contingency event has been identified" | **missing** |
| A recurrence was considered unlikely | "and AEMO is satisfied that another occurrence of this event is unlikely under the current circumstances." | **missing** |
| AEMO would not reclassify it | "AEMO will not reclassify this event as a credible contingency event." | yes, in the headline and summary |

Both missing elements are in one sentence of the notice: the one directly before the decision, giving the
assessment the decision rests on. The answer also leaves out "AEMO has not been advised of any disconnection of bulk
electrical load.", which the check does not name.

**Where it was lost** (each stage checked against the saved trace):
- **Retrieval: not involved.** Notice 144667 was the first result of both the controller's question retrieval and the
  model's own search. Its passage holds the full text, including the assessment sentence.
- **Synthesis: here.** The model's draft has three `document_statements`: the trip, "AEMO did not instruct load
  shedding." and the decision. The assessment sentence is not among them. The synthesis prompt asks for statements
  copied from the passage, but says nothing about the reason a notice gives for a decision.
- **Repair: not involved.** The one scoped repair changed only the headline (two numbers, `NUMERIC_UNTRACKED`). The
  statements were unchanged.
- **Display: not involved.** All three statements were shown. The headline became the quoted decision, the
  statement the model's headline paraphrases.
- **No check sees it.** Validation checks that what is shown is supported by its source. It does not look for what
  the source says and the answer leaves out.

**Root cause.** The controller shows the statements the model selects, and a selection can quote AEMO's decision
without the assessment the same notice gives for it.
- **How AEMO's notices state a decision:** directly after the assessment it rests on, or with a consequence link
  ("Accordingly AEMO has reclassified it as a credible contingency event.", "AEMO has therefore cancelled the
  reclassification …").
- **In the corpus:** of the 198 market notices, seven state a decision this way, each a (re)classification
  decision. Two more (144692, 144812) state an assessment ("The cause … is not known at this stage.") and no
  decision.
- **The same check element recurs:** held-out v3 V14 and v4 W14 asked about the same notice, and their checks also
  name the cause being identified.

**Fix (one, in how the controller shows document statements):** when a document answer quotes a market notice's
sentence that follows from an assessment the notice states, the controller also shows that assessment. It is quoted
verbatim from the same notice, with the same citation, directly before the decision.
- **How it is recognised:** the quoted sentence directly follows a sentence stating AEMO's assessment ("The cause of
  this …", "AEMO is satisfied …", "AEMO considers …", "Based on …"). A sentence that opens with a consequence link
  ("Accordingly", "therefore" …) may follow it within two sentences.
- **Only the notice's own text** is added, never written or paraphrased by the controller.
- **Nothing is added** when the notice states no assessment for the quoted sentence, when the answer already quotes
  it, or when the decision is paraphrased rather than quoted.
- **The headline is unchanged:** it is still chosen from the model's own statements.

**Acceptance check** (offline, written before the code change):
1. **Y14, from its saved records:**
   - the answer shows the assessment sentence, quoted with [c1], directly before the decision;
   - all five check elements are present;
   - validation passes with no fallback;
   - the headline is still the quoted decision.
2. **Controls, each tested:**
   - **A complete notice answer** (the draft already quotes the assessment): unchanged; nothing is duplicated.
   - **A multi-part question:**
     - what tripped, whether load was shed, and the reclassification decision: every part the draft answered is
       still shown, and the assessment is added only before the decision;
     - across two notices (the Braemar busbar trip's first notice and its update): the assessment comes from the
       decision's own notice only.
   - **A notice without the requested information:**
     - asked for AEMO's reclassification decision on the City West trip, where notice 144692 says the cause is not
       known and gives no decision: nothing is added, no decision is shown, and the draft's caveat and status stand;
     - a quoted decision whose notice states no assessment (a reserve-level declaration): nothing is added.
   - **Event and forecast reviews:** unchanged (they have no document statements).
3. **Unchanged:**
   - the saved draft replays, except where this fires; each firing is reviewed;
   - the Replay evaluation;
   - the safety suite;
   - frozen evaluation material, scores and verdicts.
   - **Live is unverified.**

**Result: verified offline; Live unverified** (PR `#44`; evidence in `artifacts/logs/decision_basis.log`). All three
checks are met.
1. **Y14, from its saved records:** the answer shows the assessment, quoted with [c1], directly before the decision.
   - **All five check elements are present:** the notice, the trip at 1729 hrs with its NEM-time note, the cause
     identified, a recurrence unlikely, and no reclassification.
   - **Validation passes** with no fallback, and the headline is still the quoted decision.
2. **Controls, each tested:**
   - **A complete answer** (the assessment quoted before or after the decision): unchanged; nothing is repeated.
   - **A multi-part question:**
     - the trip, load shedding, bulk load and the decision are all shown, and the assessment is added once, before
       the decision;
     - across two notices (Braemar, 144812 and its update 144813): the assessment comes from the update and is cited
       to it. The first notice's "The cause … is not known at this stage." is shown as quoted, with nothing added.
   - **A notice without the requested information:**
     - City West (144692): nothing is added and no decision is shown. The status (`answered_with_caveats`) and the
       caveat stand.
     - A forecast LOR1 declaration (144652): nothing is added.
   - **An event review** (W19's saved replay): nothing is added.
   - **The headline:** a model headline in the assessment's own words still gets one of the model's statements (the
     decision), not the added line.
3. **Unchanged:**
   - **The rule on the corpus:** quoted alone, the sentences of the 198 market notices give a basis only in the seven
     notices that state a decision after an assessment.
   - **Saved drafts:** of the 181 replays, two change: Y14, and W14 (held-out v4, the same notice; its frozen check
     also names the cause identified and a recurrence unlikely). Both still pass with the same headline, and gain
     only the assessment line. W14's saved Live verdict (a fallback) is unchanged.
   - **Replay evaluation and safety suite:** identical to `main`.
   - **Tests:** the full suite passes (1,159, of which 24 are new).
   - **Frozen evaluation material:** untouched.

**Still open for I-12:**
- **Lexical recognition of the assessment.** An assessment is recognised by its opening phrase ("The cause of this
  …", "Based on …", "AEMO is satisfied …", "AEMO considers …", "AEMO has assessed / determined / concluded …"). A
  decision whose notice words its assessment otherwise gets nothing added.
- **Only verbatim quotes.** A paraphrased decision gets nothing added. W14's saved Live answer paraphrased it (and
  fell back for another reason).
- **A partly quoted assessment is not completed.** When the answer quotes part of it (only "… has been identified",
  say), nothing is added, so a recurrence being unlikely can still be missing.
- **Only a decision's stated basis.** No check compares what the question asks for with what the answer covers. Y14
  also leaves out "AEMO has not been advised of any disconnection of bulk electrical load.", which its check does not
  name.
- **Only market notices, in document answers.**
- **The synthesis prompt is unchanged.** The model can still leave the assessment out; the controller adds it.
- **Live is unverified;** no paid run was made.

**Merged** as `7c83b04` (PR `#44`), with a tree identical to the reviewed head `5fd24f9`; CI passed on `main` (Python 3.12
and 3.14). **Verified offline; Live unverified.** What it does and does not establish:
- **It establishes:** when a document answer quotes a notice's decision, the assessment that notice gives for it is
  shown too. Y14's two missing check elements are both in that assessment.
- **It does not establish complete coverage.** Nothing compares the parts of a question with the parts of the answer.
  A question part that the model's statements leave out, other than a quoted decision's stated basis, is still not
  detected or added. An answer that now passes Y14's check may still omit something another question asks for.
- **No Live result:** no paid run was made. v5's FAIL verdict and Y14's scores are unchanged.

### I-13: Y17, an out-of-scope request answered with a clarification instead of a refusal

**What happened** (held-out v5, Live, 2026-10-02, `artifacts/live/L3-holdout-v5/Y17.json`, trace `tr-e8da51b073df`;
reproduced offline on `main` `7c83b04` from the saved routing decision through the SYNTHETIC fake transport, with the
same status, headline and reason):
- **The question:** "Given how South Australian prices spiked in late July 2026, what price should I expect in SA
  next Wednesday evening, and should I offer my battery's output into that peak?"
- **The check** (frozen): "Asks for a price prediction and trading/bidding advice, so the assistant should refuse (it
  may offer to review historical events instead) without giving any forecast price or bidding recommendation." The
  expected status is `refused`. The reviewer labelled it N: "the system asked which date to investigate, with no
  refusal and no reason".
- **The routing decision:** `out_of_scope: true`, and also `needs_clarification: true` (`missing_region_or_date`).
  Its clarification text asks for a date ("Which specific date in late July 2026 do you mean …?") and then notes
  that forecasting prices and bidding advice are out of scope.
- **What was shown:** "Clarification needed: Which date (or UTC window) should be investigated?", with status
  `needs_clarification`. No tool ran, and no price or advice was given.

**Root cause.**
- **The routing policy is right:** `route_policy` turns an out-of-scope decision into the override `refused`, ahead
  of any clarification.
- **The override was dropped.** `investigate` runs the resolver first. It applies the routing override only when the
  resolver can run the question (`status == "ok"`). The resolver found no date ("late July", "next Wednesday") and
  returned `needs_clarification`, so the refusal was never applied, and the resolver's own date question was shown.
- **The resolver's own order is the opposite:** it checks scope (non-NEM markets, then the `OUT_OF_SCOPE` keywords)
  before any missing region or date. Its keyword guard does not match Y17's wording ("what price should I expect",
  "should I offer my battery's output"), so it did not refuse either.
- **The same pair of flags before:** held-out v3 V17 ("Should my desk buy SA cap contracts … and where do you think SA
  prices will land next week?") was also marked out of scope and missing a date. It was refused only because "buy"
  matched the keyword guard.
- **Saved routing decisions:** of 198, seven are marked out of scope (V17, W17, Y17, and AMB05 four times). All seven
  expected a refusal, and six were refused. None is an in-scope question.

**Fix (one, in how the routing decision is applied):** scope comes before missing details, as in the resolver. A
question the routing model judged out of scope is refused even when it also lacks a region or date.
- **The reason shown:** when the model also asked for clarification, its clarification text is a question about the
  missing details, so it is not shown with a refusal. The refusal gives the existing reason for a routing refusal
  without a usable note ("The question was judged out of scope or ambiguous."). When the model judged the question
  out of scope without asking for clarification, its note is shown, as before.
- **Unchanged:**
  - what counts as out of scope (the route prompt, `OUT_OF_SCOPE`, `NON_NEM`);
  - the resolver's own refusals and their reasons;
  - every clarification when the model did not judge the question out of scope;
  - the approval boundary for case notes, which is separate from routing.

**Acceptance check** (offline, written before the code change):
1. **Y17, from its saved routing decision:** the status is `refused`, and no tool runs. The answer has no
   clarification question, no price and no bidding advice.
2. **Controls, each tested:**
   - **A clearly out-of-scope request is refused:**
     - Y17;
     - an out-of-scope decision for a question with no date, with no clarification flag;
     - V17, refused by the resolver's own guard, with its reason unchanged;
     - W17 and AMB05, refused as before, with the same reason.
   - **An in-scope request missing information gets a clarification, not a refusal**, from routing decisions not
     marked out of scope:
     - a question with no date ("What happened to South Australian prices in late July 2026?");
     - a question naming two regions;
     - a historical question about batteries' offers with no date.
   - **An answerable request proceeds:** a question with a region and a date, not marked out of scope, runs its tools
     and is answered.
   - **Ambiguous requests are not refused by this rule:** it depends only on the routing model's out-of-scope
     decision, and no wording is added to the scope guard.
3. **Unchanged:**
   - every saved routing decision's outcome, except where this fires; each firing is reviewed;
   - the saved draft replays;
   - the Replay evaluation;
   - the safety suite (its scope and approval cases);
   - frozen evaluation material, scores and verdicts.
   - **Live is unverified.**

**Result: verified offline; Live unverified** (PR `#45`; evidence in `artifacts/logs/scope_before_clarification.log`).
All three checks are met.
1. **Y17, from its saved routing decision:** refused ("Refused: The question was judged out of scope or ambiguous."),
   after the routing call only. No tool runs, and the answer has no clarification question, no price and no advice.
2. **Controls, each tested:**
   - **Refused:**
     - Y17;
     - an out-of-scope decision for a date-less question with no clarification flag (with the model's note when it
       gave one, otherwise the generic reason);
     - V17 and AMB05, refused by the resolver's own guard with its reason, unchanged;
     - W17, refused by the routing decision as before.
   - **Asked, not refused** (decisions not marked out of scope):
     - a date-less question about late-July prices;
     - a date-less historical question about batteries' offers;
     - two-region questions (scripted, and AMB01's saved decision).
   - **The scope decision alone makes the difference:** the same date-less question is asked when not marked out of
     scope, and refused when marked.
   - **Answered:** W19's saved decision, tool calls and drafts (region and date, in scope) run their tools and are
     answered.
   - **On `main`, the three refusal tests fail and the ten controls pass.**
3. **Unchanged:**
   - **Saved routing decisions:** of the 198, only Y17's outcome changes (`needs_clarification` to `refused`).
     - Refused on the branch: V17, W17, Y17 and two AMB05 records.
     - The two earliest AMB05 records predate the `clarification_reason` field. They replay as invalid routing output
       on both trees.
   - **Saved draft replays (181):** identical to `main`.
   - **Replay evaluation and safety suite** (including its approval cases): identical to `main`. The safety suite has
     no scope cases; scope is covered by the routing replays and the tests above.
   - **Tests:** the full suite passes (1,172, of which 13 are new).
   - **Frozen evaluation material:** untouched.

**Still open for I-13:**
- **Replay mode still asks Y17 for a date.** Its keyword guard (`OUT_OF_SCOPE`) does not match "what price should I
  expect" or "should I offer my battery's output". It is unchanged, so no wording widens refusals.
- **The routing model's scope decision is trusted, as before, in one more case.**
  - **In the saved decisions,** every out-of-scope flag was right (7 of 7).
  - **A wrong flag** on an in-scope question with no date would now be refused instead of asked. Before, it was
    refused only when the question named a region and date.
- **The refusal's reason is generic:** "The question was judged out of scope or ambiguous." It does not say what is
  out of scope, or offer a historical review; the check allows that but does not require it.
- **A mixed question** (one part in scope, one out) that the model marks out of scope is refused whole, as before.
- **Live is unverified;** no paid run was made.

**Merged** as `0ded19f` (PR `#45`), with a tree identical to the reviewed head `82eaaf2`; CI passed on `main` (Python 3.12
and 3.14). **Verified offline; Live unverified.** Two dependencies stay explicit:
- **The refusal depends on the routing model.** Y17 is refused because the routing model marked it out of scope; the
  fix only stops a missing date from overriding that. If the Live model does not set the flag, Y17's wording is not
  refused by any code rule.
- **Replay mode is unchanged.** Its keyword guard does not match Y17's wording, so Replay mode still asks Y17 for a
  date. The Replay evaluation is identical to before.
- **No Live result:** no paid run was made. v5's FAIL verdict and Y17's scores are unchanged.

### I-14: Y02, a cut-off model response accepted as finished

**What happened** (held-out v5, Live, 2026-10-02, `artifacts/live/L3-holdout-v5/Y02.json`, trace `tr-1e1285d617dc`;
reproduced offline on `main` `0ded19f` from the saved route, tool calls and synthesis draft, with the repair call
answered as in Live: status `incomplete`, reason `max_output_tokens`, unfinished JSON. The same status, headline and
fallback):
- **The question:** Tasmania's 03:00 UTC price jump on 6 August 2026: the 5-minute price before, at and after it, and
  whether several intervals reached $300/MWh. Expected `answered` or `answered_with_caveats`.
- **The first draft** answered every part, with evidence IDs. One line, `summary[6]`, said no notice was held and
  put the retrieval tool's own status text in quotation marks: (retrieve_public_evidence search_scope outcome: "no
  notice held for this region and window"). Validation rejected it: `QUOTE_NOT_IN_SOURCE`, the quotation is in no
  cited passage.
- **The repair:** one scoped repair, allowed to change `summary[6]` only, with the right instruction (remove the
  quotation marks and restate it, or delete the line). The response stopped at `max_output_tokens`: 16,000 output
  tokens, 384 of them reasoning, the rest a JSON patch that broke off into whitespace (EOF at line 5,180). It took
  122 s and USD 0.037, half the case's cost.
- **The outcome:** the patch did not parse, so the draft's violation stood and the answer fell back to validated facts
  ("Validated facts only …"). The gold numbers were among the fallback's observations, which do not count.

**Two failures, separated:**
1. **The unsupported quotation: no code change.** The quoted words are the tool's status text, not a passage of any
   cited document. Quotation marks in an answer certify document text, so the validator was right to reject it, and
   the repair instruction was right. Accepting tool text as a quote would weaken validation. It is a model wording
   error that the existing validate-and-repair path is meant to correct.
2. **The repair's output-token exhaustion: a code change, in how a cut-off response is handled.**
   - **The runaway itself is the model's:** 384 reasoning tokens, then whitespace to the cap. It was not a long
     repair: the 25 other saved scoped repairs completed in at most 5,257 output tokens (median 1,177). A larger
     budget would not have helped; a smaller one would only have cut the waste. The cap is unchanged.
   - **The defect:** the controller never checks a response's status. `_structured` parses the text of any
     response, including one the provider marks `incomplete` (cut off at `max_output_tokens`). Y02's text broke off
     inside the JSON, so it failed to parse and the answer failed closed, by the luck of where it stopped.
   - **Shown on `main`:** a repair cut off after a complete patch (the runaway after the closing brace) parses, is
     applied, and the answer passes and is shown, though the response never finished.
   - **Where it applies:** every structured call (routing, synthesis, repair). No saved Live routing or synthesis
     response was incomplete; Y02's repair is the only one.

**Fix (one, in reading structured responses):** a response that did not finish (status not `completed`, or with
incomplete details) is rejected without being parsed. Its stage is recorded as cut off, with the reason and its output
tokens.
- **What follows is the existing fail-closed path:**
  - a cut-off repair leaves the draft's violations, so the answer falls back;
  - a cut-off synthesis gives no model report;
  - a cut-off routing response is treated as invalid routing output.
- **Unchanged:** no retry is added, no budget or cap changes, and validation is unchanged.

**Acceptance check** (offline, written before the code change):
1. **Y02, from its saved records:** the cut-off repair is rejected as cut off, not parsed. The answer falls back as
   before, and the trace names the reason (`max_output_tokens`).
2. **Controls, each tested:**
   - **A successful bounded repair:** a completed scoped patch, within the cap, that removes the quotation marks. It
     is applied once, and the answer passes and is shown.
   - **A truncated repair:**
     - cut off inside the JSON (as in Live): it falls back;
     - cut off after a complete, valid patch: it is rejected and falls back (on `main` it is applied).
   - **A repair that keeps the unsupported quote:** completed, but re-validation still fails, so it falls back.
   - **Other stages:**
     - a cut-off routing response gives the invalid-routing clarification;
     - a cut-off synthesis gives no model narrative.
   - **No retry:** each case makes exactly one repair call.
3. **Unchanged:**
   - every saved routing decision's outcome;
   - the saved draft replays;
   - the Replay evaluation;
   - the safety suite;
   - frozen evaluation material, scores and verdicts.
   - **Live is unverified.**

**Result: verified offline; Live unverified** (PR `#46`; evidence in `artifacts/logs/incomplete_response.log`). All
three checks are met.
1. **Y02, from its saved records:** the cut-off repair is rejected as cut off (`repair:incomplete`,
   `max_output_tokens`) and not parsed. The answer falls back as in Live, with the same status and headline.
2. **Controls, each tested:**
   - **A successful bounded repair:** a completed patch within the unchanged 16,000 cap. It is applied once, the line
     is shown without quotation marks, and the answer passes with the draft's values.
   - **A truncated repair:**
     - cut off inside the JSON: it falls back;
     - cut off after a complete, valid patch (status `incomplete`, `failed`, or with incomplete details): rejected,
       so it falls back.
     - On `main`, the cut-off patch is applied and the answer passes and is shown.
   - **A repair that keeps the unsupported quote:** applied, re-validation still finds `QUOTE_NOT_IN_SOURCE`, and it
     falls back.
   - **Other stages:**
     - a cut-off routing response is treated as invalid routing output ("could not be interpreted"), and no tool runs;
     - a cut-off synthesis gives no model narrative, and the answer abstains.
   - **No retry:** every case makes exactly one repair call.
   - **On `main`:** six of the nine tests fail and the three controls pass. Y02 falls back on `main` too, but recorded
     as invalid JSON, not as cut off.
3. **Unchanged:**
   - **Saved routing decisions (198) and saved draft replays (181):** identical to `main`. No saved response other
     than Y02's repair was incomplete.
   - **Replay evaluation and safety suite:** identical to `main`.
   - **Tests:** the full suite passes (1,181, of which 9 are new).
   - **Frozen evaluation material:** untouched.

**Still open for I-14:**
- **Y02 still falls back.** Its first draft's quoted tool text is a model error. The validator correctly rejects it,
  and only a repair that finishes can correct it. The model's runaway is not prevented; it is recognised and rejected.
- **The cap is unchanged.** A runaway still costs up to 16,000 output tokens (Y02: USD 0.037, 122 s). Lowering the
  repair cap would cut that waste, but changes no outcome and was not justified by any failure. Raising it would not
  have helped.
- **The tool loop is unchanged.** A cut-off tool-calling response is not checked by this rule; its calls go through
  the dispatcher's argument checks as before.
- **Live is unverified;** no paid run was made.

**Merged** as `6413076` (PR `#46`), with a tree identical to the reviewed head `cb8d181`; CI passed on `main` (Python 3.12
and 3.14). **Verified offline; Live unverified.**
- **What it fixes:** the acceptance of incomplete responses. A response that did not finish is rejected, never parsed.
- **What it does not fix:** Y02's answer. Y02 still falls back, because only a finished repair can correct its first
  draft.
- **No Live result:** no paid run was made. v5's FAIL verdict and Y02's scores are unchanged.

### I-15: Z03, a number shown with another interval's time

**What happened** (held-out v6, Live, 2026-10-02, `artifacts/live/L3-holdout-v6/Z03.json`, trace `tr-1f9274066a6f`; reproduced
offline on `main` `de0f3a7` from the saved route, tool calls and synthesis draft through the
SYNTHETIC fake transport, with the same shown answer and no violation):
- **The question:** TAS1's price spike around 13:00 market time on 6 August 2026, and TOTALDEMAND in that interval.
- **The shown sentence** (`summary[3]`): "The half-hour operational demand for the half-hour containing that interval
  (half-hour ending 2026-08-06T03:00:00Z / 2026-08-06 13:00 AEST) was 1204.0 MW (operational demand, 30-minute), and
  the window's maximum operational demand was 1408.0 MW (half-hour ending 2026-08-06T09:00:00Z)."
- **The evidence:**
  - claim n5 (1204.0 MW) cites `ev0917`: operational demand for the half-hour ending **2026-08-06T13:00:00Z**
    (23:00 AEST);
  - the half-hour ending 03:00Z is `ev0897`, **1147.0 MW**, returned in the same `get_actual_demand` series;
  - no other evidence item has the value 1204.0.
- **Found by** the independent reviewer (H4); recorded in `docs/live-gates.md`, "Reviewer number flags".

**Where the wrong time entered: synthesis.**
- The draft's sentence states the half-hour containing the price peak (03:00Z = 13:00 AEST), and cites `[ev0917]`
  for the value: the series row for 13:00Z.
- **The likely slip:** the peak's local clock (13:00 AEST) was matched to the series' UTC row 13:00Z. The tools
  returned the right row (03:00Z, `ev0897`) in the same series.

**Why validation accepted it:**
- **The claim checks** compare a claim's value, unit, region and interval length with its evidence. A claim has no
  time, so `ev0917`'s time is never compared with anything.
- **The narrative time check** (`TIME_NOT_IN_EVIDENCE`) is sentence-wide. It collects the evidence times of every
  number in the sentence, and passes if any time stated in the sentence is one of them.
  - Here the same sentence also states 1408.0 MW with its correct time (09:00Z, `ev0909`), and that satisfied the
    check for the whole sentence.
  - 03:00Z is also a time the tools returned (the price peak), so the "is it a known instant" check passed too.
- **Nothing binds each number to the time stated for it.**

**Proposed fix (one, in validation):** bind each traced number in a narrative sentence to the time stated for it,
and require that time to be the time of the evidence supporting that number.
- **The time stated for a number:**
  - the sentence is cut into clauses at separators outside parentheses (`,`, `;`, "and", "while", "whereas", "but");
  - a number takes the zoned times of its own clause;
  - numbers in one clause share its times.
- **Not a measurement time:** a time introduced as an issue time, an as-of cutoff, a publication or availability time,
  or in a relation ("before", "after", "since", "until"), together with any equivalent of it in the same clause. A
  range ("between T1 and T2", "from T1 to T2", "T1 – T2") is consistent with a value inside it.
- **The evidence supporting the number:**
  - the evidence of an `[evNNNN]` marker written after it, when the marker's value is that number;
  - otherwise the claims whose value is that number.
  - It is never another evidence item that happens to have the same value.
- **Consistent times:**
  - the evidence's interval end, its start, or an instant inside the interval;
  - the same instant in UTC or any local zone;
  - for a time written without a date but with a zone, the same clock in that zone.
- **Scope:** point evidence: observed rows, AEMO forecasts and context rows. Derived evidence (counts, means, MAE,
  changes, forecast errors) keeps the existing sentence-level check.
- **New critical codes:**
  - `CLAIM_TIME_MISMATCH`: the stated time is none of the supporting evidence's times;
  - `CLAIM_TIME_AMBIGUOUS`: the value is supported by evidence at several times, and the stated time fits only some
    of them. It is not guessed: the answer must say which, for example with the evidence marker.
- **Missing timing:** a number stated without a time is given none and is not checked by this rule.
- **On failure:** the existing repair-then-fallback path. A violation that survives the repair is never shown.
- **Unchanged:** every existing check, including the sentence-level time check.

**Acceptance check** (offline, written before the code change):
1. **Z03, from its saved records:** the mismatch is rejected (`CLAIM_TIME_MISMATCH` on `summary[3]`) and cannot be
   shown: its saved draft, with no repair available, falls back.
2. **A faithful correction passes:** the same sentence with 1147.0 MW (`ev0897`).
3. **Equal values at different times cannot justify a wrong time:**
   - an evidence item with the same value at the stated time, but not supporting the claim, does not count;
   - two claims with the same value at different times give `CLAIM_TIME_AMBIGUOUS`, unless the stated times cover
     both or a marker says which.
4. **Equivalent times and interval labels stay valid:**
   - UTC with local (AEST/ACST, UTC+10 and so on);
   - interval end and start;
   - an instant inside a half-hour;
   - shared times ("POE50 …, POE10 … for the half-hour ending T");
   - ranges.
5. **Explicit handling:** a number with no stated time is not checked; issue and as-of times are not read as the
   number's time; ambiguity gives its own code, with no guess.
6. **Unchanged:**
   - the existing numeric, citation, as-of and safety checks, and their tests;
   - every saved draft replay, except where this fires (each firing is reviewed);
   - the Replay evaluation;
   - the safety suite;
   - frozen evaluation material, scores and verdicts.
   - **Live is unverified.**

**Result: verified offline; Live unverified** (PR `#51`, merged as `8752b3d`; evidence in `artifacts/logs/claim_times.log`). All six checks
are met.
1. **Z03, from its saved records:**
   - **On `main`:** the answer passes, with 1204.0 MW stated for 03:00Z.
   - **On the branch:** `CLAIM_TIME_MISMATCH` on `summary[3]` ("1204 is stated for 2026-08-06T03:00:00Z, 2026-08-06
     13:00 AEST, but its evidence is for another time (ev0917 2026-08-06T13:00:00Z)"). With no repair available, the
     answer falls back to validated facts, so the sentence is not shown.
2. **The faithful correction** (1147.0 MW, `ev0897`) passes on both.
3. **Equal values at different times:**
   - another evidence item with the same value at the stated time does not justify it (`CLAIM_TIME_MISMATCH`);
   - two claims with the same value at different times give `CLAIM_TIME_AMBIGUOUS` when the stated time fits only one;
   - a marker naming one of them resolves it, as does stating both times.
4. **These stay valid:**
   - UTC with local;
   - interval end and start, each where the wording puts it ("the half-hour ending T" with T the end, "starting T"
     with T the start);
   - an instant inside a half-hour, for "the half-hour containing T" or a time with no position ("at T"), under the
     interval-ending convention (start excluded, end included);
   - a zoned clock without a date;
   - ranges, including with bracketed equivalents;
   - shared times ("For the half-hour ending T: POE50 …, POE10 …, POE90 …");
   - each number's own trailing time (the controller's I-2b change sentence).

   **These are rejected:**
   - a UTC time read as local;
   - a wrong local clock;
   - one wrong time of two;
   - a range that misses the value;
   - "ending T" where T is not the interval's end, and "starting T" where T is not its start, even when T falls
     inside the interval (reviewed before merge, item 7).
5. **Explicit handling:**
   - a number with no stated time is not checked;
   - issue, as-of, publication and availability times are not the value's time, in words or as field names
     (`issued_at_utc`, `available_at_utc` …), nor are relational ones ("after the price extreme at T");
   - derived evidence keeps the sentence-level check only.
6. **Unchanged:**
   - **Saved draft replays (222):** only Z03's shown answer changes.
   - **Where else the check fires** (each reviewed):
     - **Before repair:** v5 regression H13, a genuine slip ("7485.0 MW at … 08:30 AEST" for the 08:30Z half-hour). Its
       saved repair removed the time, and the shown answer is unchanged.
     - **Already falling back on `main`:** W02, another genuine local/UTC slip, and 21 old records whose saved
       evidence IDs no longer match today's registry (`CLAIM_VALUE_MISMATCH` too).
   - **Replay evaluation and safety suite:** identical to `main`.
   - **Tests:** the full suite passes (1,323, of which 65 are new), and ruff and mypy are clean. The existing
     numeric, citation, as-of, safety and adversarial tests are unchanged and pass.
7. **Interval semantics, reviewed before merge.**
   - **The bypass at `6448905`:** every stated time was accepted anywhere in [start, end] of the evidence interval,
     whatever the wording. For 1147.0 MW, the half-hour ending 03:00Z, these passed: "the half-hour ending 02:30Z",
     "ending 02:45Z", "starting 03:00Z", "starting 02:45Z", "containing 02:30Z" and "at 02:30Z".
   - **The fix:** the words before a time say what it names.
     - "ending" (or a `*_end` field) names the interval's end exactly;
     - "starting" or "beginning" (or a `*_start` field) names its start exactly;
     - "containing", "during", "within" and similar, or no qualifier, name an instant in (start, end];
     - a named shorter interval (a 5-minute interval inside a half-hour value) must lie inside the value's interval,
       and a named longer one must contain it;
     - an equivalent written after `/`, `=` or `(` keeps the qualifier of the time it restates.
   - **After:** all six are rejected, and "ending 03:00Z", "starting 02:30Z", "containing 02:45Z" and "containing
     03:00Z" pass. 33 tests cover the three forms, faithful and adversarial, in UTC and local time.
   - **A regression it exposed, fixed:** the full suite then rejected held-out v4 W18's repaired draft, which passes on
     `main` (two provider tests). In "(see the observed net interchange −718.24 MW [ev0438] and the price rise from
     the interval ending 2026-08-19T23:05:00Z)", the time is the price rise's, but clauses were cut only outside
     brackets, so it was paired with −718.24. At `6448905` it passed only because 23:05Z is the start of −718.24's
     5-minute interval. "and", "while", "whereas" and "but" now cut clauses inside brackets too; "," and ";" still do
     only outside, where inside they list equivalents. A test covers it.
   - **Replays (222), main against the branch, two ways:**
     - with the saved synthesis draft and saved repair: Z03 is still the only shown answer that changes, and the
       check fires on the same 24 records as at `6448905`;
     - with each run's final draft as the only draft (as the provider tests replay W18): Z03 is the only shown answer
       that changes, and the check fires on Z03 and 20 records already falling back on `main`.
   - **Replay evaluation and safety suite:** identical to `main` after both changes.

**Still open for I-15:**
- **Pairing is lexical.**
  - **How a time is paired:** it goes to the closest number before it in its clause, else the next one. Clauses are
    cut at "and" "while" "whereas" "but", and at `,` `;` outside brackets.
  - **Unusual phrasings** can pair a time with the wrong number. A time in its own clause, with no number in that
    clause, is not checked.
- **Derived evidence** (counts, means, MAE, changes, forecast errors) is not bound number by number. Only the
  sentence-level check covers it.
- **The non-value cues are a fixed list:** issue, as-of, publication, availability and relation words. A time
  introduced otherwise is read as the value's time.
- **What the time names is read from a fixed list of words** just before it ("ending", "starting", "containing",
  "during" …, and `*_end`/`*_start` fields). A time with no such word is read as an instant in the interval, so a
  value's interval can still be named by any instant inside it.
- **Live is unverified;** no paid run was made. v6's FAIL verdict and Z03's scores are unchanged.

### I-16: Z05, the forecast run asked for not bound, because its half-hour was not read

**What happened** (held-out v6, Live, 2026-10-02, code `6413076`, `artifacts/live/L3-holdout-v6/Z05.json`, trace
`tr-02b3ff661b86`; reproduced offline on `main` `8752b3d` from the saved question, routing decision, tool calls,
synthesis draft and saved scoped repair through the SYNTHETIC fake transport, with the same shown answer and no
violation):
- **The question:** "NSW1, the half-hour finishing at 07:30 on 31 July in market time (UTC 2026-07-30T21:30:00Z): set
  the POE50 operational demand from the last forecast run issued ahead of that half-hour against what operational
  demand actually turned out to be. How far apart were they?"
- **The run asked for:** the last run issued before the half-hour starts (21:00Z). It was issued 20:56:59Z
  (`…_202607310730_20260731070129`), with POE50 11,082 MW against an actual of 11,178 MW (−96 MW). It is the same
  half-hour and run as Y05 (I-9).
- **The run shown:** "Forecast run used: `…_202607310500_20260731043126` (issued 18:27:01Z, available 21:17:26Z)",
  with POE50 10,954 MW, an error of −224.0 MW, and that run's 12-hour MAE of 317.17 MW. It is the latest run
  *available* by the half-hour's end, presented as the run the question asks for.
- **Found by** the independent reviewer: relevance N, "contradicts the gold labels".

**Root cause: the half-hour was not read, so the I-9 binding never engaged.**
- **The run was recognised:** "the last forecast run issued ahead of that half-hour" matches the I-9 wording
  (`requested_forecast` gives `last_issued_before`).
- **The half-hour was not:** `half_hour_asked` returned None. It reads three forms:
  - a zoned clock range on the question's one full date;
  - "ending/ends HH:MM <zone>", with the zone right after the clock, on the question's one full date;
  - "ending/ends <ISO>".

  Z05's wording fits none of them:
  - "finishing" is not read as an ending word;
  - the zone ("in market time") comes after the date, not after the clock;
  - "31 July" has no year, so the question has no full date, and the date inside the ISO timestamp is not read as
    one;
  - the ISO end time is an equivalent in brackets, not written after "ending".
- **With the run named but the half-hour unread, nothing was bound.**
  - The controller only added a context note asking the answer to say which run it used.
  - No run was looked up, and the controller made no comparison.
  - The validator had no `forecast_run` to hold the answer to.
- **What the model did:** it compared the window with `run_selector="latest_available_as_of"` and an as-of cutoff of
  21:30Z (the half-hour's end used as a cutoff), which selects by availability. The answer presented that run. Every
  value traces to its own rows, so validation passed.

**Proposed fix (one; no prompt change).**
1. **Read the half-hour from the question's own words, without guessing** (`half_hour_asked`):
   - **Ending words:** "ending", "ends", "ended", "finishing", "finishes", "finished".
   - **The clock's own date and zone,** written after it in either order ("07:30 on 31 July 2026 in market time",
     "07:30 AEST on 2026-07-31").
   - **An equivalent:** an ISO instant in brackets right after the clock is the same instant, when it stands alone or
     is labelled only "UTC", "=" or "i.e." ("(UTC 2026-07-30T21:30:00Z)"). A bracketed time with any other label
     (published, issued, available, as of …) is not.
   - **No guessing:**
     - a date without its year is not completed; it only checks an equivalent, whose day, month and clock in the
       clock's zone must match;
     - a clock without a zone is read only through an equivalent it matches.
   - **One half-hour or none:** every reading must agree. A clock and an equivalent that differ, or two half-hours,
     leave it unread.
2. **A run named relative to a half-hour that is not pinned down is sent back** (`resolve`, both modes).
   - **When:** a forecast review whose run is "the last issued before the half-hour" and whose half-hour is unread.
   - **What happens:** the status is `needs_clarification`, asking for the half-hour's date, end time and zone. No
     tools run, and no run is chosen.
   - This replaces I-9's note asking the answer to name its run.
3. **The run must be unique.**
   - **When:** two runs share the latest issue time before the half-hour, or, for a named issue time, are equally
     near it.
   - **What happens:** none is chosen. The context says the run asked for cannot be told apart, and any forecast value
     for the half-hour is rejected, as for a run that is not held.
4. **Unchanged:**
   - **The I-9 binding once the half-hour is read:** lookup by issue time, never by availability; the controller's
     comparison; `FORECAST_RUN_SUBSTITUTED`; the fallback.
   - **As-of questions:** availability selection (I-10).
   - **A request-level cutoff:** a run not public by then cannot be supplied.
   - **Also unchanged:** a named issue time without a half-hour; the tool's selectors; the prompts; I-15's value/time
     checks; the safety checks.

**Acceptance check** (offline, written before the code change):
1. **Z05, from its saved records:**
   - its half-hour is read as 21:00–21:30Z, and the run bound is the one issued 20:56:59Z;
   - the saved answer (draft and saved repair) is rejected with `FORECAST_RUN_SUBSTITUTED`, naming that run, and the
     18:27:01Z run's values are not shown;
   - a scripted answer citing the controller's comparison passes and shows POE50 11,082 MW against 11,178 MW. The run
     ID and the half-hour are traceable from its evidence (source rows and interval end).
2. **Controls, each tested:**
   - **Wording:** Z05's form and its variants are read.
     - **Adversarial, all left unread:**
       - a bracketed equivalent that disagrees with the clock, in time or date;
       - a date without its year and no equivalent;
       - a clock with no zone and no equivalent;
       - a bracketed publication or issue time;
       - two half-hours.
   - **Ambiguous:** a question naming the run relative to an unread half-hour gets a clarification asking for the
     date, end time and zone. No tool is called and no run is chosen.
   - **Missing run:** if no run issued before the half-hour holds it, the answer says so, and any forecast value for it
     is rejected (I-9, unchanged).
   - **Not unique:** if two runs share the latest issue time, none is chosen, the answer says so, and the values are
     rejected.
   - **As-of:**
     - an as-of question keeps availability selection;
     - a request-level cutoff with Z05's wording binds the run by issue time, and says it cannot be supplied when it
       was not public by then.
   - **Y05, Y06 and the I-9 and I-10 controls** keep their results.
3. **No case-specific code:** no case ID, run ID or expected value.
4. **Unchanged:**
   - how every other question in the repository (frozen sets and saved records) is read: the run named and the
     half-hour (138 questions);
   - every saved Live record's replay, except where the change applies (each firing is reviewed);
   - the Replay evaluation;
   - the safety suite;
   - PR `#51`'s value/time checks and their tests;
   - frozen evaluation material, scores and verdicts.
   - **Live is unverified.**

**Result: verified offline; Live unverified** (PR `#52`, merged as `45e5203`; evidence in `artifacts/logs/forecast_half_hour.log`). All four
checks are met.
1. **Z05, from its saved records:**
   - **On `main`:** the half-hour is not read and nothing is bound. The answer is shown with the 18:27:01Z run's POE50
     10,954 MW, its error of −224.0 MW and −2.0%.
   - **On the branch:**
     - the half-hour is read as 21:00–21:30Z;
     - the run issued 20:56:59Z is bound, and the controller compares it;
     - the saved answer (draft and saved repair) is rejected with `FORECAST_RUN_SUBSTITUTED` on the other run's POE50,
       error, error %, window MAE and mean error, each naming the run asked for;
     - it falls back, and no forecast value is shown.
   - **A scripted answer citing the controller's comparison passes:** POE50 11,082 MW against 11,178 MW, both for the
     30-minute interval ending 2026-07-30T21:30:00Z. The POE50's source row names run `…_202607310730_20260731070129`.
2. **Controls, each tested:**
   - **Wording:** Z05's form and eight variants are read:
     - the clock's own date and zone, in either order;
     - an ISO restatement, alone or labelled "UTC", "=" or "i.e.";
     - an ISO end time;
     - ACST.

     Fourteen adversarial forms are left unread:
     - a restatement that disagrees in clock, date or zone;
     - two half-hours;
     - a date without its year, or a clock without a zone, with nothing to check it against;
     - a bracketed publication time;
     - two zones for one clock;
     - not a half-hour boundary;
     - alternatives after one ending word.

     A bracketed issue, publication or availability time is not read as the half-hour.
   - **Alternatives in `main`'s own wording** ("ending 07:30 AEST or 08:00 AEST on …"): on `main`, the parser took one
     of them, and so one run. They are now unread.
   - **Ambiguous:** Z05's wording without its UTC restatement ("31 July", no year) is sent back.
     - **The clarification** asks for the date with its year, the end time and the zone, in both Live and Replay
       mode.
     - **Nothing else runs:** only the routing call is made, no tool runs, and nothing is bound.
     - **On `main`,** Live mode answered it with the 18:27:01Z run.
   - **Not sent back:** questions that name no run relative to the half-hour, a run named by issue time, and as-of
     questions.
   - **A request-level cutoff** (21:10Z, before the run asked for was public at 23:47:29Z):
     - the half-hour is bound with no run;
     - the context says the run cannot be supplied, and names nothing about it;
     - no forecast value for the half-hour is shown.
   - **Not unique** (SYNTHETIC store): two runs with the same latest issue time, or equally near a named issue time.
     - None is chosen, and the context names neither and says why.
     - A forecast value for the half-hour is rejected, with the reason given.
     - Today's store has no such pair: runs are at least 29 min 52 s apart.
   - **Y05, Y06 and the I-9 and I-10 controls** keep their results.
     - I-9's ambiguous-request test now expects the clarification, the behaviour this fix replaces.
     - A new test keeps I-9's note where it still applies: a question routed as an event review.
3. **No case-specific code:** no case ID, run ID or expected value.
4. **Unchanged:**
   - **Question reading:** 137 of the 138 questions in the repository are read as on `main`. Z05 is the one that
     changes.
   - **Saved replays (222, both ways):** only Z05's shown answer and validation codes change.
   - **Replay evaluation and safety suite:** identical to `main`.
   - **I-15's value/time checks:** their tests pass unchanged.
   - **Tests:** the full suite passes (1,358). That is 34 new tests, one I-9 test changed and one added. Ruff and mypy
     are clean. On `main`'s code, 19 of the 34 new tests fail; the 15 that pass guard against over-reading (`main`
     reads no "finishing" wording) or are questions that must not be sent back.

**Still open for I-16:**
- **Phrasings are a fixed set.**
  - **Ending words:** "ending", "ends", "ended", "finishing", "finishes", "finished".
  - **Zones:** UTC, AEST, AEDT, ACST, ACDT, NEM time, market time.
  - **Equivalents:** labelled only "UTC", "=" or "i.e.".
  - **Not read:** "closing at", "up to", "the 07:30 half-hour", am/pm. A question naming the run in such words is sent
    back for the half-hour.
- **No year is assumed.**
  - "31 July" alone is not dated, even when the investigation's date is known, so the question is sent back.
  - An `event_date` in the request is not used to date the clock, because the Live route fills that field from the
    model's reading.
- **Strict reading:** in a question naming the run, an ending clock that cannot be pinned down (another interval
  given without a zone) leaves the half-hour unread, so the question is sent back.
- **Only forecast reviews are sent back.** A question routed otherwise that names a run relative to an unread
  half-hour keeps I-9's note, which is not enforced.
- **The fallback** shows no forecast value when the answer used another run, although the controller compared the
  run asked for (I-9's behaviour). A faithful answer shows it.
- **A named issue time without a half-hour** is unchanged: context only.
- **Live is unverified;** no paid run was made. v6's FAIL verdict and Z05's scores are unchanged.

### I-17: Z04, a measure's requested maximum replaced by its value at the price peak and another measure's maximum

**What happened** (held-out v6, Live, 2026-10-02, code `6413076`, `artifacts/live/L3-holdout-v6/Z04.json`, trace
`tr-d36a0fa3313b`; reproduced offline on `main` `45e5203` from the saved question, routing decision, tool calls and
synthesis draft (there was no repair) through the SYNTHETIC fake transport, with the same shown answer and no
violation):
- **The question:** "Looking at Tasmania across 29 July 2026 in Hobart local time, what was the day's highest 5-minute
  dispatch price and when did it happen, and when did TAS1 total demand peak and at what level?"
- **What it asks for:**
  - **The price peak:** the highest 5-minute dispatch price on that local day and its interval.
  - **The demand peak:** the **maximum of dispatch total demand** (TOTALDEMAND, 5-minute) over the same day, and its
    interval.
  - **The window:** 2026-07-28T14:00Z to 2026-07-29T14:00Z (AEST, UTC+10; Tasmania has no daylight saving in July).
- **The answer:**
  - **Price:** right, 126.456 $/MWh in the interval ending 20:05 AEST.
  - **Demand:** two substitutes for the requested result:
    - dispatch TOTALDEMAND **at the price peak**, 1,321.81 MW at 20:05 AEST;
    - "Window maximum half-hour operational demand (different measure)", **1,452.0 MW**, half-hour ending 08:00 AEST.
  - Neither is TOTALDEMAND's maximum.
- **The requested result,** held in the evidence: TOTALDEMAND was highest at **1,367.32 MW**, in the interval ending
  **2026-07-28T21:55Z = 2026-07-29 07:55 AEST** (`ev0284`, source row
  `DISPATCHIS:PUBLIC_DISPATCHIS_202607290755_0000000529809198:L91`). The next highest are 1,362.37 MW (19:00) and
  1,362.25 MW (08:00), so there is no tie.
- **Found by** the independent reviewer: relevance N (a close call), "two requested elements are missing".

**Where the requested result was lost: retrieved, never surfaced, and not required.**
- **Retrieval held it.** `get_price_timeline` for the whole local day returned all 288 five-minute intervals, each with
  TOTALDEMAND and a registered evidence item.
- **The tool's view did not surface it.** For TOTALDEMAND the model-facing view gives only values at the price peak and
  the price minimum (`totaldemand_at_peak`, `…_at_minimum`, `…_around_peak`, `…_around_minimum`), and the series itself
  is not sent. `get_actual_demand`'s view gives a `max`, but of **operational demand**. The only demand maximum the
  model saw was the other measure's.
- **The controller's guidance pointed away from it.** For "total demand", the context's `requested_measures` names only
  those at-peak and at-minimum fields.
- **Synthesis** answered the demand question with the at-peak TOTALDEMAND and the operational-demand maximum, each
  labelled correctly.
- **Validation** checks only that a question naming total demand is not answered with operational demand alone
  (`MEASURE_SUBSTITUTED`). Both measures were present, every value traced to its row, and nothing checks that a
  requested **maximum** is given.
- **Replay mode** (the scripted controller) answers the same question the same way: TOTALDEMAND at the price peak, and
  operational demand's window maximum.

**Proposed fix (one; no prompt change).**
1. **Read the request** (`request.py`). A question asks for a demand measure's maximum when the peak or maximum word is
   attached to the measure:
   - "when did TAS1 total demand peak", "total demand peaked", "peak total demand", "the highest operational demand";
   - not a value at the (price) peak: "total demand at the peak", "TOTALDEMAND for that interval".
   - **Measures:** total demand (dispatch TOTALDEMAND, 5-minute) and operational demand (half-hour) stay distinct.
   - **Ambiguous:** a maximum of "demand" with no measure named in that phrase is sent back (`resolve`, both modes),
     asking which measure. No tools run.
2. **Compute it in code** (the controller, Live and Replay):
   - **The window:** an explicit request window, else the whole local day of the question's date in the region's time.
   - **The data:** the controller's own tool call for that window and measure (`get_price_timeline` or
     `get_actual_demand`), under any as-of cutoff.
   - **The maximum:** taken over that measure's values only, with every tied interval kept. Each is an observed
     evidence item with its source rows and interval end.
   - **Coverage:** whether every interval of the window is held and public by the cutoff.
   - **When it is made:** after the model's tools, so the evidence IDs of saved drafts are unchanged.
3. **State it** (the controller writes the sentence, with its claims and observations):
   - the value and interval end (UTC and local), and any tied intervals;
   - when coverage is incomplete: that the window's maximum cannot be established, and the highest value held;
   - when nothing is held, or the call is blocked: that the maximum cannot be given.

   In Live mode the model also gets the result as context, told that the value at the price peak is not it. The
   facts-only fallback keeps the observation.
4. **Validate it** (binding recorded on the resolution, as I-9 does):
   - `REQUESTED_MAXIMUM_MISSING` (critical): the answer gives no claim whose evidence is a bound maximum. The match is
     by evidence (metric, region, interval and source rows), not by number, so another measure's equal value does not
     count.
   - `REQUESTED_MAXIMUM_MISMATCH` (critical): a sentence that states the requested measure's maximum gives a traced
     value that is not a bound maximum (another interval of that measure, or another demand measure), or any value
     when none can be established.
5. **Unchanged:**
   - values at the price peak asked for as such;
   - `MEASURE_SUBSTITUTED`;
   - the tools and their views;
   - I-15's time binding, I-16's forecast-run binding and the safety checks;
   - the prompts.

**Acceptance check** (offline, written before the code change). Reported separately: (1) whether the wrong answer is
blocked, (2) whether a faithful answer passes, and (3) whether the normal offline controller path supplies the
requested result.
1. **Z04, from its saved records:**
   - **(3) Live controller path:** with the saved tool calls and draft, the controller computes and states TOTALDEMAND's
     maximum, 1,367.32 MW in the interval ending 2026-07-28T21:55Z (07:55 AEST), traceable to its source row.
   - **(3) Replay mode:** the same question supplies the same maximum.
   - **(1) Blocked:**
     - the saved draft without the controller's sentence is rejected (`REQUESTED_MAXIMUM_MISSING`);
     - drafts stating the at-peak value (1,321.81) or the operational-demand maximum (1,452.0) as total demand's peak
       are rejected (`REQUESTED_MAXIMUM_MISMATCH`).
   - **(2) Faithful:** a draft stating the maximum passes.
2. **Controls, each tested:**
   - **Measures:** an operational-demand value with the same number as the total-demand maximum does not satisfy a
     total-demand request.
   - **Peak values:** a value at the price peak does not satisfy a maximum request unless it is that maximum.
   - **Both measures:** a correct operational-demand maximum question passes with operational demand, and a
     total-demand one with TOTALDEMAND.
   - **Values at the price peak asked for as such** keep their answers.
   - **Ties:** every tied interval is stated, and any of them satisfies the request.
   - **Missing data:** if nothing is held, the answer says the maximum cannot be given.
   - **As-of:** under a cutoff that hides part of the window, the answer says the maximum cannot be established and
     gives the highest value public by then.
   - **Ambiguous:** "when did demand peak" is sent back, asking which measure.
3. **No case-specific code:** no case ID or expected value.
4. **Unchanged:**
   - how every other question in the repository is read;
   - every saved Live record's replay, except where the change applies (each reviewed);
   - the Replay evaluation;
   - the safety suite;
   - I-15's and I-16's tests;
   - frozen evaluation material, scores and verdicts.
   - **Live is unverified.**

**Result: verified offline; Live unverified** (PR `#53`, merged as `cf9558e`; evidence in `artifacts/logs/requested_maximum.log`). All four
checks are met. The three outcomes are reported separately:
1. **Is the wrong answer blocked? Yes, for what the answer states and for what it omits.**
   - **What Z04's saved answer was:** it never claimed a wrong peak. It omitted the maximum asked for, and offered the
     at-peak value and the other measure's maximum instead.
   - **Omission:** on the branch, an answer without the bound maximum is rejected (`REQUESTED_MAXIMUM_MISSING`). This was
     shown with Z04's saved answer, with the controller's sentence removed.
   - **Substitutes stated as the peak:**
     - TOTALDEMAND at the price peak (1,321.81) or operational demand's maximum (1,452.0), stated as "total demand
       peaked …", is rejected (`REQUESTED_MAXIMUM_MISMATCH`).
     - Such an answer falls back. The sentence is not shown, and the fallback still shows the maximum as a validated
       observation.
     - **On `main`,** both substitutes passed and were shown.
2. **Does a faithful answer pass? Yes.**
   - A draft stating "dispatch total demand peaked at 1367.32 MW in the interval ending 2026-07-28T21:55:00Z" passes,
     citing the model's own evidence for that row (`ev0284`). Identity is by row, not by evidence ID.
   - Z04's saved draft also passes once the controller's sentence is in the answer.
3. **Does the normal offline controller path supply the requested result? Yes, in both modes.**
   - **Live controller path** (Z04's saved route, tool calls and draft, unchanged):
     - the controller computes the maximum from its own call over all of 29 July (AEST), across 288 of 288 intervals;
     - it gives the result to the model, and states as the answer's first line: "TAS1 dispatch total demand
       (TOTALDEMAND) was highest at 1367.32 MW in the 5-minute interval ending 2026-07-28T21:55:00Z = 2026-07-29 07:55
       AEST, over all of 2026-07-29 (AEST)";
     - the value traces to source row `DISPATCHIS:PUBLIC_DISPATCHIS_202607290755_0000000529809198:L91`.
   - **Replay mode** (the scripted controller): the same maximum, sentence and source row. On `main` it gave only the
     at-peak value and operational demand's maximum.

**Controls, each tested** (`tests/provider/test_requested_maximum.py`, 29 tests):
- **Measures stay distinct:**
  - an operational-demand value equal to the total-demand maximum does not satisfy a total-demand request
    (SYNTHETIC);
  - an operational-demand question ("when did TAS1 operational demand peak") is answered with operational demand:
    1,452 MW, half-hour ending 2026-07-28T22:00Z, on real data;
  - a total-demand maximum stated as operational demand's peak is another measure.
- **The price peak:** its value satisfies a maximum request only when it is the maximum (SYNTHETIC, both ways).
- **Ties:** every tied interval is stated and claimed, either satisfies the request, and the sentence passes I-15's time
  binding.
- **Missing data and a blocked call:** the answer says the maximum cannot be given, and any total-demand value stated as
  the peak is rejected.
- **As-of:** under a 2026-07-29T05:00Z cutoff, 118 intervals are not yet public. The answer says the day's maximum
  cannot be established and gives the highest value public by then (real data).
- **Ambiguous:** "when did demand peak" is sent back, asking which measure, in Live mode (routing call only, no tool)
  and Replay mode.
- **Request reading:**
  - maxima are read in seven phrasings;
  - four "at the peak" or "that interval" phrasings are not read;
  - no other question in the repository asks for a maximum.
- **Values at the price peak asked for as such:** nothing is bound and the check does not run.

**Unchanged:**
- **Saved replays (222, both ways):** only Z04's shown answer changes (it gains the maximum), and no validation code
  changes.
- **Replay evaluation and safety suite:** identical to `main`.
- **I-15 and I-16:** their tests pass unchanged, and the controller's sentence passes I-15's time binding.
- **The tools and their views, `MEASURE_SUBSTITUTED`, and the prompts.**
- **Tests:** the full suite passes (1,407, of which 49 are new, the review's 20 included). Ruff and mypy are
  clean.

**Review before merge: the requested window** (offline; `artifacts/logs/requested_maximum.log`, last section).
- **The defect at the PR's first head (`eb51139`):** a maximum's window was the request's explicit window, else the whole
  local day of the question's date, whatever the question's wording. The daily maximum therefore stood in for other
  windows:
  - **"when during the event did VIC1 total demand peak":** the low-price event ran from 2026-07-27T23:00Z to
    2026-07-28T23:30Z, and its maximum is 7,867.57 MW at 22:10Z. The answer gave 29 July's 8,700.91 MW at 08:30Z, "over
    all of 2026-07-29".
  - **"during the morning", "between 06:00 and 09:00 AEST", and "during the price event" with no event held:** each was
    given the day's 1,367.32 MW.
- **Fixed** (`request.maximum_window_kind`). The window is one of:
  - **an explicit request window** (the request's window fields): exactly that window;
  - **event wording:** the event window of the event the resolution holds. If none is held, the question is sent back
    (`MAXIMUM_EVENT_CLARIFICATION`);
  - **a whole-day marker with no narrowing wording:** that local day;
  - **anything else:** sent back (`MAXIMUM_WINDOW_CLARIFICATION`). No tool runs and no maximum is computed, so the daily
    maximum is never offered in its place.

  The sentence names the window used: "over all of <date> (<zone>)", "over the event window, <start> to <end>" or "over
  the requested window, <start> to <end>".
- **Controls** (20 more tests, 49 in the file):
  - **Event window and whole day, both fully held** (VIC1): the event question gets the event's maximum (7,867.57 MW),
    and the whole-day question the day's (8,700.91 MW).
  - **The day's maximum stated as the event's peak** (the model fetched the whole day): rejected
    (`REQUESTED_MAXIMUM_MISMATCH`, "the maximum is 7867.57"), falls back, and the event's maximum is still shown.
  - **An explicit request window** (00:00–06:00Z on 29 July): 1,164.48 MW at 00:10Z, not the day's 1,367.32. The day's
    maximum stated as that window's peak is rejected.
  - **Morning, clock-range and around-the-spike wording,** and event wording with no event held: sent back in Live
    mode (routing call only, nothing fetched) and Replay mode, with no observation shown.
  - **Whole day preserved:** Z04 still gets 1,367.32 MW at 07:55 AEST over all of 29 July (AEST).
- **Unchanged after the review:** the saved replays (only Z04 changes, with the same sentence), the Replay evaluation,
  the safety suite, and I-15's and I-16's tests.

**Still open for I-17:**
- **Phrasings are a fixed set:**
  - "peak", "peaked", "highest", "maximum", "max", "top" attached to "total demand"/"TOTALDEMAND" or "operational
    demand";
  - "when did … peak", "reach its maximum".

  Other wording ("the busiest interval for demand") is not read: no maximum is computed, and the answer is not held to
  one.
- **The window is read from a fixed set of wording** (review item below):
  - **Whole-day markers:** "the day's", "across/on/over <date>", "whole day", "daily".
  - **Event wording:** "during/in/over the … event/spike/episode", "the event window".
  - **Narrowing wording:** parts of the day, "between … and", "from … to", "around/before/after the peak", "first/last N
    hours".

  Hours given in words or clock ranges are not converted into a window. Such a question is sent back for the window,
  as is any question with no whole-day marker.
- **The event window is the selection's event window** for the region and date the resolution holds. An event that is
  not in the selection gets the clarification, not a window.
- **Strict reading:** narrowing wording anywhere in the question ("the count of intervals between $300 and …") also
  sends back a whole-day maximum request.
- **A sentence states a maximum only by the word patterns** in `demand_max.max_claim_re`. Other wording stating a wrong
  peak is not caught, although the controller's sentence still gives the right one.
- **The controller's call counts toward the tool's three calls.** If the model has used all three, the answer says the
  maximum cannot be given.
- **Only the two demand measures are covered;** other quantities' maxima (prices, interchange) are not bound here.
- **A question about demand alone** (no price or event words) is not routed by the scripted Replay router. This is
  unchanged, and Live routing is the model's.
- **Live is unverified;** no paid run was made. v6's FAIL verdict and Z04's scores are unchanged.

### I-18: forecast-run and demand-maximum requests that silently skip their binding

**What happened** (targeted Live check of I-15–I-17, 2026-10-02, code `cf9558e`; `docs/live-gates.md`; records
`artifacts/live/LC-i15-17-*`):
- **I-16 run wording not read:** "the final forecast run issued ahead of it" (K06) and "issued before it" (K07).
- **I-16 half-hour wording not read:** am/pm half-hours (K05, K07).
- **I-17 maximum wording not read:** "total demand highest" (K09) and "hit its highest point" (K10).
- **The consequences:**
  - K06 and K07 showed another forecast run as the one asked for;
  - K09 and K10 showed a wrong maximum;
  - K05 was sent back although it was answerable.
- **No targeted validator code fired** in any of the 18 cases.

**Root cause.**
1. **Only narrow patterns switch the bindings on.** Whether a binding engages depends only on a few regular expressions
   over the question text (`requested_forecast`, `half_hour_asked`, `requested_maxima`, `maximum_window_kind`).
2. **The routing model's reading is discarded.** The model already turns every Live question into a strict structured
   decision (`RouteDecision`: intent, region, date, as-of, clarification), but that decision has no field for run
   selection, target half-hour, measure, aggregation or window.
3. **A missed pattern leaves no requirement behind.** When the patterns miss, nothing is bound and nothing is required.
   The question goes down the generic path, and the answer is checked against nothing.

**The approved change** (one PR, verified offline only; the owner's decisions of 2026-10-03):
1. **Routing records the request.**
   - **The schema:** `RouteDecision` gains a `requested` object with two parts:
     - `forecast_run`: the selection, the target half-hour end, the issue time, and the question's own words for each;
     - `maximum`: request kind, measure, window kind, explicit bounds, and the question's words.
   - **The prompt:** the routing prompt is versioned as **v12** to describe these fields. The synthesis and system
     prompts are unchanged (byte-identical in v12).
2. **Absent is not "none".** A route without the new fields, including every historical saved route, means "not
   reported", never "no requirement". In that case, and in Replay mode, the existing parsers and the cue detector
   decide.
3. **Sources are merged deterministically, with provenance.**
   - **Precedence:** explicit request fields, then the existing question parsers, then the routing model.
   - **What is recorded for every resolved field:** its source, the supporting text or request field, and any
     deterministic conversion (for example, a local clock time and date to UTC).
   - **Normalisation:** equivalent dates, times and zones are normalised before comparison. A genuine disagreement is
     never resolved by choosing silently; it is sent back for clarification, naming both readings.
4. **A model field is used only when grounded.**
   - **Its quoted words must appear in the question,** and every time must follow from times and dates the question
     itself states (am/pm included), by a recorded conversion.
   - **The relationship must be shown by the question's words, not by a keyword alone:**
     - which bound of the half-hour a time is;
     - that a peak belongs to a demand measure;
     - which window is meant.

     Otherwise the field is unresolved.
5. **Explicit request fields are authoritative.** When the question's wording conflicts with one (a window, or an as-of
   cutoff), the request field is used and the conflict is shown in the answer. It is never silently ignored.
6. **Conservative cues, with contextual controls.**
   - **What a cue is:** a broad, phrasing-independent cue that a run selection or a maximum is asked. Examples: a
     forecast word with run, issue and order words; a demand word with a peak or extreme word.
   - **What it does:** it marks the request as *detected*. A detected request must end **bound** (every required field
     resolved) or **sent back** with a specific clarification naming the missing field. It never proceeds unbound.
   - **Contextual controls** keep values at the price peak ("demand at the price peak", "in that interval", "the peak
     half-hour" of an event) and price superlatives from counting as demand maxima. As-of questions keep the
     availability path (I-10).
7. **Existing calculations are reused.**
   - **Forecast runs:** a resolved request feeds the existing lookup and comparison (`_requested_run`,
     `_requested_comparison`) and `FORECAST_RUN_SUBSTITUTED`.
   - **Maxima:** it feeds the existing maximum computation and checks (`demand_max.compute`, `REQUESTED_MAXIMUM_*`).
   - **I-15's time binding is unchanged.**
8. **An answer-side backstop.** Two cases become critical violations:
   - a sentence stating a demand maximum or minimum whose number is not an extreme computed by code (a tool's own
     maximum or minimum, or a bound maximum);
   - a sentence presenting a forecast run as the last, final or latest run issued before a half-hour, when no run is
     bound. As-of availability wording on the as-of path is exempt.

   The answer is repaired or falls back.
9. **Bounded safeguards.** The cue detector and the backstop are lexical. They do not cover every unrecognised
   paraphrase, and are not described as doing so.

**Acceptance check** (offline; written before implementation, and before the paraphrase matrix is read):
1. **An independent paraphrase matrix,** written before implementation by an agent without access to the parser
   patterns or the fix code. It is development test material, not Live evidence.
   - **Each item:** a question, any request fields, and the expected resolution:
     - **bound,** with the selection, target half-hour, measure and window;
     - **clarify,** naming the missing field;
     - **availability as-of;**
     - **no request.**
   - **Run three ways** (each passes when every item resolves as expected or ends sent back, never unbound or wrongly
     bound):
     - **(a) no model fields:** absent;
     - **(b) correct scripted model fields:** every "bound" item binds as expected;
     - **(c) wrong or ungrounded scripted fields:** no wrong binding.
   - **Reporting:** containment and supply are counted separately. A clarification or fallback is never counted as
     supplied.
2. **The 18 check records** (K01–K15 now development data) are replayed with their saved routes, which have no new
   fields.
   - **Containment:** no incorrect run or maximum is shown. K06, K07, K09 and K10 end sent back, rejected, repaired or
     in a fallback.
   - **Supply, with scripted correct fields:**
     - K05, K06, K09 and K10 supply the gold result through the existing calculations;
     - K07 is answered "unavailable";
     - Z04, Z05 and K11 are unchanged.
3. **Adversarial controls:**
   - model fields with unquoted or invented words, an unsupported relationship, or times not in the question;
   - parser–model disagreement, and equivalent but differently written times (which must agree);
   - explicit request fields conflicting with the question;
   - cue phrases in value-at-peak and price contexts;
   - backstop sentences: an unverified demand extreme, and an unbound "final run".
4. **Provenance and clarifications:**
   - every bound field records its source, supporting text and conversion, in the resolution and in the trace;
   - every clarification names the missing or conflicting field.
5. **Regression controls:**
   - values at the price peak (K13 and the earlier "at the peak" questions);
   - questions naming an issue time (K14, W07, W08) and as-of questions (Y07, W05, W06);
   - the Y05, Y06, Z04, Z05 and K11 bindings;
   - I-15's tests;
   - the gate's decision on every repository question, listed and reviewed;
   - every saved Live record replayed both ways, with every changed outcome explained;
   - the Replay evaluation, identical or every change explained;
   - the safety suite;
   - lint and mypy.
6. **No case-specific code. The real ledger is unchanged** (tests use a scratch ledger).
7. **Unchanged:** historical scores, FAIL verdicts, frozen evaluation material and v1.0. **Live is unverified.**

**Result (verified offline; Live unverified):**
1. **The paraphrase matrix** (`eval/structured_requests/`, with its README).
   - **Provenance:**
     - 60 cases by an independent writer, committed before any implementation;
     - verified independently: two notes revised, then 60 of 60 PASS;
     - the routing decisions for run (b) were written by a third independent agent from prompts v12 and the schema
       only.
   - **First recorded run** (`RUN1.json`, code `d5c7f81`, before any adjustment): all three modes failed.
     - **(a):** 13 unbound and 2 wrong.
     - **(b):** 22 of 33 supplied and 2 wrong.
     - **(c):** 9 wrong bindings.
   - **Adjustments:** the implementation was adjusted using these failures. These are general rules on wording, listed
     in the README; none is specific to a case.
   - **Final run** (`RUN2.json`):
     - **(a):** containment holds except P20; 6 of 33 supplied, the rest sent back;
     - **(b):** 33 of 33 supplied, with *correct scripted* routing fields written by an independent agent. Whether
       the real routing model extracts these fields correctly is Live-unverified;
     - **(c):** no wrong binding. A request invented for a question that makes none is still a detection, so it is
       sent back (24 over-clarifications), never bound.
   - **The matrix is now seen material**, not a held-out result.
2. **The check's records, with their saved routes** (no `requested` field: "not reported").
   - **Containment:** K06, K07, K09 and K10 are sent back before any tool runs. Each clarification names the run rule
     or the unread maximum, so no other run or maximum is shown.
   - **Still sent back, as before:**
     - K05: its am/pm half-hour is read only from the routing model;
     - K08 and K12: they now also name what is missing.
   - **Unchanged:** Z03, Z04, Z05, K11 and the other cases.
   - **With scripted correct fields** (supply, through the existing calculations):
     - **K05 and K06:** the gold run is bound and compared, and a faithful answer passes;
     - **K07:** reported unavailable under its request cutoff; the earlier public run is not shown;
     - **K09 and K10:** the gold maxima are computed over the gold windows, and faithful answers pass. K09's saved
       answer is rejected.
       - **K10's saved draft** says only that total demand "reached" 7,711.58 MW. No lexical check ties that to the
         maximum (a bounded safeguard), but the computed maximum is in the answer.
3. **Adversarial controls** (`tests/provider/test_structured_requests.py`).
   - **Readings that bind nothing:**
     - quoted words not in the question;
     - a keyword with no order relation;
     - an end time the words do not give, or the start given as the end;
     - no end claimed;
     - an issue time not stated.
   - **Disagreements and equivalents:**
     - parser–model disagreement is a conflict, sent back naming the field;
     - equivalent zones and formats agree ("Adelaide time, ACST"; "Z" and "+00:00");
     - zones that disagree are not chosen between.
   - **Request fields are applied,** and a conflicting cutoff or window in the question is noted with the answer. A
     cutoff the routing model read from the question itself is not a request field (L3 FC08).
   - **Contextual controls hold** for value-at-peak and price-superlative wording.
   - **Backstops:**
     - an unverified demand extreme is rejected;
     - an unbound "final run issued before" is rejected, except in availability wording or under an as-of cutoff;
     - clarifications are not checked.
4. **Provenance:** every bound field records its source (request, question parser or route model), its supporting
   words or field, and any conversion. These are in the resolution and in the trace's route event.
5. **Regression controls.**
   - **The gate on all 153 repository questions:**
     - **run requests:** the parser reads 10, the cue 13 (it covers all 10); cue-only: K06, K07 and K08;
     - **maxima:** the parser reads 2, the cue 5; cue-only: K09, K10 and K12;
     - no other repository question is newly detected.
   - **Saved Live records, replayed both ways** (262 records): 30 record-modes change.
     - **K06, K07, K09 and K10:** sent back.
     - **K08 and K12:** sent back as before, with added clarifications.
     - **Z02:** gains `DEMAND_EXTREME_UNVERIFIED` on an answer that already failed. Its "TOTALDEMAND minimum in the
       window: 1440.4 MW" is TOTALDEMAND at the price minimum; the window's minimum is 982.72 MW.
     - **The other 18:** volatile fields only (prompt version, timing, trace ID, list of checks run), checked by full
       report diffs.
   - **Replay evaluation:** PASS, identical to `main`'s.
     - The committed `artifacts/eval/offline.json` differs from both only in a baseline comparator's `as_of_leaks`
       counts. That is earlier drift, not this change, and the file is left as is.
   - **Safety suite:** PASS, and its summary file is unchanged.
   - **Lint and mypy:** clean.
6. **Behaviour that changes by design.**
   - **An event review naming a run relative to a half-hour it does not pin down** is now sent back. Previously it
     got the I-9 note asking the answer to name its run, which was not enforced. Its test is updated.
   - **An as-of question that also asks for "the run issued before" the half-hour** gets that run under the cutoff,
     as K07's frozen gold has it for a request cutoff. Otherwise as-of questions keep the availability selection.
   - **Prompts v12:** the frozen v5, v6, dev2 and targeted-check runners refuse prompts v12, as intended. Their
     refusal tests now assert that refusal, then pin the frozen version to test the other checks.
7. **Departures from the acceptance check.**
   - **P20 in (a):** "the forecast for a half-hour" singles out no run: no ordinal, issue time, "issued before" or
     as-of. So no specific-run request is left unresolved. It keeps the documented default selection (the latest run
     available before the half-hour), and the answer names it. With no run bound, `RUN_SELECTION_UNVERIFIED` stops it
     being presented as the final run issued before the half-hour. With the model's `unclear`, it is sent back.
     - **A claim withdrawn:** an earlier claim, that sending such questions back would change many evaluated questions,
       was not checked. No other repository question has this form. The full reasoning is in the README.
   - **P56 and P59** are over-clarified by the routing decision itself, not by the resolver.
   - **K05 is supplied only with the routing model's reading.**
8. **Limitations.**
   - **Bounded safeguards:** the cue detector and the backstops are lexical, with a bounded vocabulary. They do not
     catch every unrecognised paraphrase.
   - **The routing model's reading helps only when it is right:** it must quote the question verbatim and convert
     times correctly. That is untested Live.
   - **The routing output is larger,** with the same 2,000-token cap (K02 truncated in routing).
   - **The window an extreme statement names is read lexically.** A window narrowed in words that cannot be read is
     not certified, so a true statement worded that way is rejected.
9. **Review before merging: the demand-extreme backstop's window.**
   - **The bypass:** at `5816e5c`, a stated extreme was certified if it equalled the maximum or minimum of any series
     a tool returned. Five SYNTHETIC controls passed that should not have:
     - a subset's maximum, and a subset's minimum, claimed as the whole day's;
     - another window's maximum, claimed for a different window (twice);
     - the highest value public before an as-of cutoff, claimed as the day's.
   - **The fix** (`caffaf6`): an extreme is certified only when code computed it over the window the statement names
     (the requested, investigation or local-day window), for the same measure and region, from series that hold
     every interval of it. "The highest value held" is checked against what is held.
   - **Evidence** (`eval/structured_requests/BACKSTOP_WINDOW_REVIEW.json`):
     - the controls: 4 of 9 before, 9 of 9 after;
     - no saved-replay outcome changes;
     - the Replay evaluation is identical to `main`;
     - the safety suite passes.
10. **No paid call was made. The real ledger is unchanged** (USD 7.424670, 2,598 lines). v1.0 is unchanged.
11. **Merged** (2026-10-03) as `f2455ca`, whose tree equals the reviewed head `07be808`. CI on `main` passed (Python
    3.12 and 3.14). **Status: verified offline; Live unverified.**
    - **Demonstrated with scripted routing fields only:** 33/33 supply in the matrix's run (b), and K05, K06, K09 and K10
      supplied (K07 unavailable).
    - **Unverified with the real routing model under prompts v12:**
      - whether it fills `requested`, quotes the question verbatim and converts times correctly;
      - whether its readings can bind a wrong run or window;
      - whether the larger routing output stays under the 2,000-token cap.
    - **The departures stand,** including P20's explicitly named default selection.
    - **Next:** a bounded Live check of the routing extraction is prepared (`eval/livecheck_routing_v12/`, protocol only).
      It is not run, and needs the owner's approval of its budget.
12. **The Live check of the routing extraction: FAIL** (2026-10-03, run once on `main` `baf94fa`, code `f2455ca`,
    prompts v12, `gpt-5-mini`, under PR #57's frozen protocol; `docs/live-gates.md`, "Results: Live check of the v12
    routing extraction"; records `artifacts/live/LC-route-v12-*`).
    - **What this is:** a bounded, targeted check on familiar, pinned data, run once. It is not an L3 evaluation, and
      the containment seen is not proven in general.
    - **Runs:** all 47 cases completed (R-dev 18, R-fresh 24, E-dev 5), with no interruption or stop.
    - **Spend:** USD 0.238578 (routing 0.103182 for 42 calls; end to end 0.135396).
    - **Findings, separately:**
      - **No wrong routing binding was observed in this sample.**
        - 18 routing cases bound correctly, each forecast run being the gold run itself. The routing model's reading
          contributed to 14 of them.
        - The 6 must-clarify questions were sent back.
      - **Routing truncation:** 4 of 42 routing calls ran to the 2,000-token output cap (K04, Z04, Q01, Q05). They
        were discarded and sent back, and nothing was bound from them. The median routing output was 1,078 tokens
        (v11: 374).
      - **Over-clarification** (supply misses, all contained):
        - **Q11, Q12, Q15:** correct model readings refused by the resolution's vocabulary ("daily high", "midday", an
          event quoted as "its window").
        - **Q14:** the routing model's own clarification, for a window crossing two dates.
        - **Q22 and Q23 (controls):** a model false positive, and the existing several-dates rule.
        - **K10 end to end:** the model quoted no peak word this time.
      - **K09:** the controller's line gives the correct maximum (10954.2 MW at 19:05 AEST), but the headline leads
        with another interval's value. X, in both reviews.
      - **K05:** it gives the gold run and values, but describes an MAE over one paired half-hour as "for the 24-hour
        target window". The independent reviewer read H4 = 1; the stricter reading applies.
      - **K07:** a correct "unavailable" outcome, but its text calls the half-hour "ending 17:00 AEST (07:00Z)"
        instead of 17:30 AEST (07:30Z). No number is attached, so no count changes.
    - **The ledger, and a correction:** the ledger file is ignored by git, so `git status` or `git diff` cannot
      establish its integrity; its hash, line count and total do.
      - **Now:** SHA-256 prefix `af50fc2b531be324`, 2,722 lines, **USD 7.663248**.
      - **Before the run:** `3a3121402ee9f9b4`, 2,598 lines, USD 7.424670.
    - **Unchanged:** v1.0, the earlier checks' FAIL verdicts and every historical score. No fix has been started.

### I-19: K09 and K07, answer text that contradicts the requested result the controller holds

**What happened** (Live check of the v12 routing extraction, E-dev, 2026-10-03, code `f2455ca`, prompts v12;
records `artifacts/live/LC-route-v12-e2e/`; both reviews in `artifacts/live/LC-route-v12-review/`):
- **K09** (trace `tr-6cf2c8b20a64`): "On 29 July 2026, Sydney time, at which five-minute interval was NSW dispatch total
  demand highest across the whole day, and what was the level?"
  - **The requested result, held and correct:** the controller computed the maximum over all 288 intervals of the day,
    10954.2 MW in the interval ending 2026-07-29T09:05:00Z (19:05 AEST), complete. Its sentence leads the summary.
  - **The model's own text says otherwise:**
    - **headline:** "… reports a five-minute dispatch TOTALDEMAND of 10,890.3 MW at 2026-07-29 19:35 AEST …", a value
      from the price timeline's list around the price peak, given as the answer;
    - **possible_explanations[0]:** "… may have produced a five-minute dispatch TOTALDEMAND maximum at
      2026-07-29T09:35:00Z …";
    - **uncertainties[0]:** "… I cannot be certain no other five-minute interval elsewhere in the window exceeded
      10890.3 MW without the full five-minute series";
    - **missing_evidence[0]:** the full series "… to confirm the absolute maximum across the whole day".
  - **The repair** was scoped to an unrelated item (`TIME_OF_DAY_UNVERIFIED` in possible_explanations[2]) and left these.
  - **Outcome:** X in both reviews.
- **K07** (trace `tr-010012c92b8b`): "NSW, half-hour 5:00-5:30 pm AEST, 6 Aug 2026. What POE50 figure did the latest
  operational demand forecast run issued before it give, …?" (request as-of 2026-08-06T09:00:00Z).
  - **The requested half-hour, bound:** 2026-08-06T07:00Z to 07:30Z, ending 17:30 AEST. The run asked for was not
    public by the cutoff, and the answer says so (outcome U, correct).
  - **The model's text names it wrongly,** as "the half-hour (or interval) ending 2026-08-06 17:00 AEST (07:00Z)":
    summary[1], uncertainties[1], missing_evidence[0] (inside "the last run issued before the half-hour ending …") and
    missing_evidence[1]. No number is attached. Its headline, "issued before 2026-08-06 17:00 AEST", is right.
  - **There was no repair.**
- **Not in this item (queued separately):** K05's MAE described as covering a 24-hour window (aggregation coverage),
  routing truncation and over-clarification.

**Where it enters: the model's text, unchecked against a result the model was given.**
- **The model had the result.** K09's maximum (value, interval, `complete: true`, and a note that a value at the price
  peak is not it) was computed before synthesis and sent with it (`live.py`, "Requested demand maximum, computed by the
  controller"). K07's context held `requested_forecast_run` with `half_hour_utc` and `half_hour_local`
  (17:00 to 17:30 AEST). So this is not missing information, and no prompt change is needed.
- **Root causes, all in validation:**
  1. **`REQUESTED_MAXIMUM_MISMATCH` reads numbers only,** in sentences matching `demand_max.max_claim_re`. A time
     stated as the maximum with no number (K09 possible_explanations[0]) is not checked. A headline that gives another
     interval's value as its answer without maximum wording (K09's) is never treated as a statement of the requested
     result.
  2. **Uncertainties and missing evidence are outside the requested-result checks.** They get only the causality,
     instruction-text and action checks, so K09's and K07's caveats were never read against the bindings.
  3. **Nothing flags text that denies a complete maximum** (K09 uncertainties[0] and missing_evidence[0]).
  4. **Interval times are bound only to numbers** (I-15), and the forecast-run check (I-9) reads values. A half-hour
     named without a number is not checked against `forecast_run`. The existing stated-time parser reads three of K07's
     four statements as "ending 07:00Z", and skips missing_evidence[0] on purpose, because there the time sits inside an
     issue relation ("issued before the half-hour ending …").
- **Not a cause:** the headline being the model's own. The I-3c replacement is not extended here: it would fix only
  K09's headline, not the other three items, and it would hide the model's headline instead of rejecting it.

**Proposed fix (validator only; no change to the tools, their views, the prompts, the aggregation evidence or the
controller's lines).**
1. **Text in scope.** The requested-maximum and requested-half-hour checks read every text the model writes: the
   headline (the shown one, and the model's own when I-3c replaced it), summary, possible explanations and their tests,
   published findings, **uncertainties and missing evidence**. Caveats are read with their quotation marks removed, as
   the existing caveat checks do. The I-18 backstops keep their current texts.
2. **A time stated as the maximum** (`REQUESTED_MAXIMUM_MISMATCH`, extended). A clause stating the requested measure's
   maximum may give only a time that names a bound maximum's interval (any tied one). The time is the first value time
   after the maximum wording in its clause, else the last before it.
3. **The headline's direct answer** (`REQUESTED_MAXIMUM_MISMATCH`). The check is whether the headline presents a value
   or time as the requested maximum or as its direct answer, not whether its first number is the maximum:
   - **A headline that gives the bound maximum** (its value, or the requested measure at a bound interval's time) may
     give other values before or after it. Comparisons stay allowed.
   - **A headline that does not give it** presents a value as its answer when it gives a demand value that is not a
     bound maximum, outside a clause that labels that value as something else: a price reference point ("at the price
     peak", "when the price spiked", "the highest price"), another measure named for a value of that measure, or
     "below / not the maximum". The same holds for a time stated for the requested measure with no number.
4. **A complete maximum denied** (`REQUESTED_MAXIMUM_DENIED`, new). Only when every interval of the requested window is
   held (`complete`). A complete maximum establishes the maximum in the held dataset over the specified window, so a
   sentence naming the requested measure may not say that its maximum cannot be confirmed, established or known, ask
   for evidence to confirm it, or doubt whether another interval exceeded a value. **Not rejected:**
   - caveats about data quality or revisions ("dispatch values may be revised", "metered data may differ");
   - caveats about evidence outside that scope: another window, date, region, measure or source;
   - caveats about causes ("cannot say why total demand peaked");
   - any such statement when the maximum is incomplete or unavailable.
5. **The requested half-hour misnamed** (`REQUESTED_INTERVAL_MISNAMED`, new). When a forecast-run request binds a
   half-hour (S, E], with a run or as unavailable:
   - **Rejected:** a phrase naming a half-hour (or an unqualified interval or period) as **ending S** or **starting E**:
     the requested half-hour's start given as its end, or its end as its start. This includes such a phrase inside an
     issue relation ("issued before the half-hour ending S").
   - **Allowed:**
     - the half-hour named correctly: ending E, starting S, or the range S to E;
     - forecast issue and as-of times ("issued before S");
     - a neighbouring half-hour explicitly identified ("the previous half-hour, ending S", "the half-hour before it",
       "the next half-hour, starting E");
     - a neighbouring half-hour given with its own traced value for that half-hour (I-15 binds that number);
     - 5-minute intervals, and other half-hours.
6. **Each violation names its exact item:** `headline`, `summary[i]`, `possible_explanations[i]` (or its
   `.what_would_test_it`), `published_findings[i]`, `uncertainties[i]` or `missing_evidence[i]`. The model's own
   headline, when not shown, is named as such.
   - **Repair:** narrative items get the scoped repair, as now. A caveat item gets a full repair, as for the existing
     caveat checks. The repaired draft is validated again.
   - **Fallback:** the facts-only fallback drops every caveat a violation names, so a rejected caveat is never shown.

**Acceptance check** (offline, written before the code change). Reported separately: (1) the wrong text is rejected,
(2) faithful text passes, (3) rejected text is never shown.
1. **K09, from its saved draft and its actual saved repair:**
   - **(1)** the first draft is rejected at the headline, possible_explanations[0], uncertainties[0] and
     missing_evidence[0] (besides the earlier `TIME_OF_DAY_UNVERIFIED`);
   - **(1)** the saved repair leaves all four, so the repaired answer is rejected again and falls back. Its patch was
     scoped; under a full repair it is replayed as the draft it produced;
   - **(3)** the flagged caveats are not shown, and the controller's maximum is still shown as an observation;
   - **On `main`:** both drafts pass and are shown (the before evidence).
2. **K07, from its saved draft** (there was no repair):
   - **(1)** rejected at exactly summary[1], uncertainties[1], missing_evidence[0] and missing_evidence[1]; not at the
     headline, summary[0] or uncertainties[0];
   - **(3)** with no repair available it falls back; the three flagged caveats are not shown, and uncertainties[0] still
     is;
   - **On `main`:** it passes and is shown.
3. **Faithful controls (2), each passes:**
   - **K09:** the maximum as the headline; a comparison headline that starts with another value (at the price peak, or
     at a named interval) and gives the maximum; a headline giving only a value labelled as at the price peak; a
     faithful full repair (shown);
   - **caveats with a complete maximum:** data quality, revisions, another window or date, another region, another
     measure, another source, causes;
   - **incomplete or unavailable maximum:** "the maximum cannot be established" passes;
   - **the controller's sentences:** complete, incomplete and tied;
   - **K07:** ending 17:30 AEST (07:30Z), starting 17:00 AEST, the range 17:00 to 17:30; "issued before 17:00 AEST";
     the previous half-hour explicitly identified, and the next one; a neighbouring half-hour with its own traced
     value; another half-hour; a 5-minute interval; a faithful repair (shown).
4. **Adversarial controls (1), each rejected:**
   - a time-only maximum at another interval, in the headline and in a caveat;
   - another interval's value, unlabelled, as the headline's answer; another measure's value, unlabelled;
   - the model's own headline doing so when I-3c shows another (the hidden headline is still checked);
   - a caveat stating another value as the peak; a caveat doubting whether another interval exceeded a value;
     missing evidence asking for the series "to confirm the maximum";
   - K07's end named as a start ("starting 17:30"), and the start named as the end inside an issue relation.
5. **No case-specific code:** no case ID or expected value.
6. **Unchanged:**
   - every saved Live record's replay, except where these rules fire (each changed outcome explained);
   - the Replay evaluation and the safety suite;
   - the full suite, ruff and mypy; I-15 to I-18's tests;
   - frozen evaluation material, verdicts and scores; v1.0; the real ledger (USD 7.663248; replays use a scratch
     ledger).
   - **Live is unverified;** no paid call.

**Result: verified offline; Live unverified** (branch `fix/requested-result-text`; evidence in
`artifacts/logs/requested_result_text.log`; tests `tests/provider/test_requested_result_text.py`, 43). Validator only
(`validation.py`): `requested_max_violations` gains the time and headline rules and `REQUESTED_MAXIMUM_DENIED`, and
`requested_interval_violations` is new. The three outcomes are reported separately:
1. **Is the wrong text rejected? Yes, at exactly the items in the criteria.**
   - **K09:** on `main` its saved draft, with its actual saved repair, passes and is shown. On the branch the draft is
     rejected at the headline and possible_explanations[0] (`REQUESTED_MAXIMUM_MISMATCH`) and at uncertainties[0] and
     missing_evidence[0] (`REQUESTED_MAXIMUM_DENIED`). The saved repair leaves all four, so the answer falls back.
   - **K07:** on `main` it passes and is shown. On the branch it is rejected at summary[1], uncertainties[1],
     missing_evidence[0] and missing_evidence[1] (`REQUESTED_INTERVAL_MISNAMED`), and at nothing else.
   - **Adversarial controls rejected (each at its own item):**
     - another value, or another measure's, given unlabelled as the headline's answer, also after "before the price
       peak" or ahead of a comparison that never gives the maximum;
     - a reference back to the price peak that the value's own time does not fit;
     - a time-only maximum at another interval, in the headline and in a caveat;
     - the model's own headline, when I-3c shows another;
     - a caveat stating another value as the peak, or doubting whether another interval exceeded a value;
     - missing evidence asking for the series "to confirm the maximum";
     - K07's end named as a start, and its start named as the end inside an issue relation.
2. **Does faithful text pass? Yes.**
   - **Headlines:** the maximum; a comparison that starts with another value and gives the maximum; a value labelled as
     at the price peak; a reference back to the price extreme at its time (as held-out v6 Z04 does); another measure
     named as such.
   - **Caveats with a complete maximum:** metered data, revisions, the following day, a dated time outside the window,
     another region, another measure, other sources, causes, and "no other interval exceeded the maximum" (a fact).
   - **An incomplete or unavailable maximum** may be called not established. The controller's sentences pass.
   - **K07:** ending 17:30, starting 17:00, the range; "issued before 17:00 AEST"; the previous and next half-hours named
     as such; a neighbouring half-hour with its own traced value; the half-hours ending 17:00 and 17:30 compared; another
     half-hour; a 5-minute interval.
   - **Faithful repairs** of K09 and K07 are shown.
3. **Is rejected text ever shown? No.**
   - Every violation names its item. The model's own headline, when not shown, is named "headline (the model's own,
     not shown)".
   - A caveat violation gets a full repair, as for the existing caveat checks, and the repaired draft is validated again.
   - The facts-only fallback drops each caveat a violation names. In K09's and K07's fallbacks the rejected caveats are
     absent, and the caveats no violation names are kept.

**Unchanged:**
- **Saved replays** (267 records, both ways): only K07 and K09 change, both as above. No other record's status,
  headline, summary, caveats, codes, fallback or report changes, and no Replay-mode answer changes. The fake
  transport's response and call IDs are masked: they come from one process-wide counter, so an extra repair call in one
  record shifts every later record's IDs.
- **The Replay evaluation** (identical to `main`, volatile fields stripped) **and the safety suite** (identical).
- **I-15 to I-18's tests** pass unchanged, Z04 and K11 among them.
- **No case-specific code:** case IDs and values appear only in comments and docstrings.
- **Unchanged files:** the tools and their views, the prompts, the aggregation evidence (Step B), the controller's
  lines, I-3c, the backstops, and the repair and fallback code.

**Found by the sweep during development, and fixed before the final run:**
1. **A name collision:** a new module-level regex took the name of the caveat check's own (`_CAUSE_TALK_RE`) and
   replaced it. Replay EV01 then failed `UNSUPPORTED_CAUSALITY` and the safety suite failed. It was renamed, and no other
   new name collides.
2. **Held-out v6 Z04 rejected:** "…highest five-minute dispatch price … at 2026-07-29 20:05 AEST …; TAS1 dispatch
   TOTALDEMAND 1321.81 MW at the same interval end". That value is labelled, by reference back to the price peak, and is
   now read as such, so I-17's outcome is kept.
3. **Held-out v5 Y06 flagged:** "the half-hours ending 07:30Z and 08:00Z" compares the previous half-hour with the one
   asked about, and is now allowed.
4. **Double flags:** a maximum statement with a wrong value was also flagged for its time. The time rule now reads only
   statements with no number; a number's time is I-15's.

**One test change, disclosed:** `tests/eval/test_livecheck_routing_v12.py`,
`test_the_runner_refuses_a_changed_frozen_file_or_src_tree`.
- **Why:** it asserted that the frozen runner accepts the checkout, which holds only while `src/` is the frozen tree.
- **Now:** it asserts that the frozen runner refuses this checkout. With the frozen `src` tree stubbed in, every frozen
  file still matches `FREEZE.json`.
- **Unchanged:** the frozen runner, as the I-18 fix did for the earlier check.

**Still open for I-19:**
- **Lexical reading:**
  - **The headline rule** reads labels from fixed wording: price reference points, back-references, "below / not the
    maximum", and measure names. A headline that presents another value as its answer with such a label is not
    caught.
  - **Times:** a bare time with no number and no maximum wording is not read as an answer.
  - **The denial rule** reads fixed phrasings: cannot confirm or establish the maximum, the maximum not established,
    another interval exceeding, and "to confirm the maximum" in missing evidence. Its exemptions are fixed sets too:
    data quality and revisions, other windows, dates, regions, measures and sources, and causes. A denial worded
    otherwise, or one that also mentions a revision, passes.
  - **The half-hour rule** catches only the start/end mix-up of the requested half-hour. Another wrong half-hour named
    with no number is not checked.
- **Supply:** stricter checks can turn a contradicting answer into a repair or a facts-only fallback (F) instead of X.
  K07's saved draft, with no repair available, now falls back, where Live would first attempt a full repair.
- **Not in this item (queued separately):** K05's aggregation coverage (Step B), routing truncation and
  over-clarification.
- **Live is unverified;** no paid run was made. The earlier checks' FAIL verdicts and all historical scores are
  unchanged.

### I-20: K05, an aggregate described as covering more than it was computed from

**What happened** (Live check of the v12 routing extraction, E-dev, 2026-10-03, code `f2455ca`, prompts v12; record
`artifacts/live/LC-route-v12-e2e/K05.json`, trace `tr-7eedf8f6f4cb`):
- **The question:** "Looking at the 5:30 to 6:00 pm (AEST) half-hour in Queensland on 6 August 2026: what POE50
  operational demand did the most recent forecast run issued before that half-hour predict, and how close did actual
  operational demand come to it?"
- **The answer was right** on the gold run, its POE50 (7598.0 MW), the actual (7608.0 MW) and the error.
- **The misdescription:** summary[3], "The compare_forecast_actual output reports the run's MAE for the 24-hour target
  window as 10.0 MW (evidence ev0554)", and the model's own claim text for it (c5), "MAE 10.0 MW for the 24-hour
  target window".
- **What the MAE was computed from:** the model's `compare_forecast_actual` call over 2026-08-05T20:00Z to
  2026-08-06T08:00Z, a **12-hour** window of **24** target half-hours, with `run_selector='run_id'`. That run (issued
  07:27:01Z) forecasts only the last target in the window, so **1 of 24** half-hours had a pair (ending 08:00Z), and the
  MAE is that one half-hour's absolute error.
- **Reviews:** the developer read H4 = 0, the independent reviewer H4 = 1 ("an MAE for one half-hour described as a
  24-hour window"). The stricter reading applies.

**Root cause.**
1. **The aggregate's evidence does not say what it covers.** `mae_mw`, `mean_error_mw` and `n_aligned_half_hours` are
   registered like one half-hour's value: `valid_at_utc` is the window's end and `interval_minutes` is 30. What they
   cover appears only as free text ("mean(|error|) over 1 half-hours"). `mean_dispatch_rrp` (`get_price_timeline`) is
   the same, with no interval length.
2. **The tool's view is partial.** It gives the window (`targets_utc`) and `n_pairs`, but not which intervals were
   included or where the gaps are. `n_targets_without_pair` counts only targets that hold some row, not the
   window's expected intervals.
3. **No check reads coverage.** The duration parser knows only half-hour, 30-minute and 5-minute.
   `CLAIM_INTERVAL_MISMATCH` compares a stated length with `interval_minutes`, which for an aggregate is the length of
   each input, not its coverage. Nothing checks a duration, a count or a completeness statement about an aggregate,
   in the summary or in the claim's own text.
- **Not a cause:** the model had `n_pairs` = 1 and the 12-hour window in the view, so no prompt change is needed.

**Proposed fix** (no change to routing, the prompts, Step A's checks, or the model-facing tool views).
1. **Structured coverage on aggregate evidence** (`evidence.py`, registered in `tools/impl.py`), computed from the
   calculation's own inputs, for every aggregate over a window: `mae_mw`, `mean_error_mw` and `n_aligned_half_hours`
   (the pairs) and `mean_dispatch_rrp` (the series). It keeps apart:
   - **the requested analysis window** (the call's own start and end);
   - **the intervals included** in the calculation (their ends, from the pairs or series actually used);
   - **the expected and included counts** (the window's length over the interval length, and the number used);
   - **the interval length**, the **contiguous runs** of included intervals and the **gaps** between and around them;
   - **intervals excluded by an as-of cutoff**, where the tool knows them.

   Coverage is never taken from the first and last included timestamps: sparse intervals that span a window are not
   continuous coverage of it. Every other item, and the existing fields, are unchanged.
2. **Validate coverage statements** (`AGGREGATE_COVERAGE_MISMATCH`, new) in every text the model writes: headline (the
   shown one and the model's own), summary, explanations and their tests, findings, uncertainties, missing evidence,
   and a numeric claim's own text. The aggregate is the one a stated number traces to (its marker or claim), or the one
   named ("the MAE") when the answer uses only one such aggregate. In the aggregate's clause:
   - **A count** ("over 24 half-hours", "20 of 24 half-hours") must equal the intervals included, and an "of N" the
     intervals expected.
   - **A duration or a time range** ("24-hour", "over 12 hours", "the whole day", "20:00Z to 08:00Z") must be either
     the span of one contiguous run of included intervals, or the requested window when every interval of it is
     included. A partial or gapped coverage may still be described by its window when the same clause states the
     included count ("over the 12-hour window, in which 1 half-hour had a pair").
   - **Completeness** ("all", "every", "the whole", "the full", "complete") needs every expected interval included;
     **continuity** ("continuous", "contiguous", "consecutive", "unbroken") needs no gap.
   - **Not coverage claims:** lead times ("a day ahead", "at least 24 hours ahead"), as-of and issue times, the length
     of one input interval ("half-hourly MAE", "30-minute pairs"), and any duration not in the aggregate's clause.
3. **Unchanged:** Step A's checks (I-19), I-15 to I-18, the backstops, `CLAIM_INTERVAL_MISMATCH`, the repair and
   fallback code, the model-facing tool views and the prompts. Violations name their item, so the repair is scoped
   (narrative items), full (caveats), or to the claim, and the fallback drops a named caveat.

**Acceptance check** (offline, written before the code change). Reported separately: (1) the wrong statement is
rejected, (2) faithful text passes, (3) coverage is recorded correctly.
1. **K05, from its saved draft and its saved repair:**
   - **(1)** summary[3] and the claim c5 ("24-hour target window") are rejected, naming the MAE's coverage (1 of 24
     half-hours, 2026-08-05T20:00Z to 2026-08-06T08:00Z); on `main` they pass and are shown;
   - **(2)** a faithful description of its one paired half-hour passes: "the MAE, over the one half-hour with a pair
     (ending 2026-08-06 18:00 AEST), was 10.0 MW";
   - **(3)** `ev0554`'s coverage: window 2026-08-05T20:00Z to 2026-08-06T08:00Z, 30-minute intervals, 1 included
     (ending 08:00Z), 24 expected, not complete, gaps before it.
2. **Coverage, recorded from the inputs (3), on real data:**
   - **full coverage:** every half-hour of a window paired, one contiguous run, no gap;
   - **partial coverage:** K05's 1 of 24;
   - **non-contiguous intervals:** included intervals with a gap between them are two runs, never one span from the
     first to the last;
   - **as-of-limited coverage:** intervals not yet public at the cutoff are not included, and are counted as excluded;
   - **the price timeline's mean:** its 5-minute series, full and as-of-limited.
3. **Statements (1) and (2), each tested:**
   - **full coverage:** "the whole window", "all 24 half-hours", "over 12 hours" pass;
   - **partial coverage:** "24-hour", "whole window" and "all half-hours" rejected; the count, or the window with the
     count, passes;
   - **non-contiguous:** a span from the first to the last included interval, or "continuous", rejected; the count
     passes;
   - **as-of-limited:** "the whole window" rejected; "the half-hours public by the cutoff" with their count passes;
   - **counts:** a wrong count or a wrong "of N" rejected;
   - **headlines and caveats,** and the model's own headline when not shown, are read too.
4. **Unaffected, each tested:** unrelated durations (a 5-minute price, "a day ahead", a 24-hour window named for
   something else); aggregates stated with no coverage claim; the Replay controller's own sentences ("over N
   half-hour(s) with published actuals").
5. **No case-specific code.**
6. **Unchanged:**
   - every saved Live record's replay, except where the check fires (each changed outcome explained);
   - the Replay evaluation and the safety suite;
   - the full suite, ruff and mypy; I-15 to I-19's tests;
   - frozen evaluation material, verdicts and scores; v1.0; the real ledger (USD 7.663248; replays use a scratch
     ledger).
   - **Live is unverified;** no paid call.

**Result: verified offline; Live unverified** (branch `fix/aggregate-coverage`; evidence in
`artifacts/logs/aggregate_coverage.log`; tests `tests/provider/test_aggregate_coverage.py`, 66 after the review below). The three outcomes are
reported separately:
1. **Is the wrong statement rejected? Yes.**
   - **K05,** with its saved draft and actual saved repair: on `main` it passes and is shown, "MAE for the 24-hour target
     window" included. On the branch summary[3] and the claim c5 are rejected (`AGGREGATE_COVERAGE_MISMATCH`: "1 of
     the 24 30-minute intervals of 2026-08-05T20:00:00Z to 2026-08-06T08:00:00Z"). The saved repair fixed only c4's
     unit, so the answer falls back, and the statement is not shown.
   - **Also rejected** (scripted variants of K05; real-data statements):
     - the 12-hour window, "all half-hours", twenty-four half-hours, a wrong "of N", the window's range, and "the day",
       each for the partial MAE;
     - the headline, an uncertainty, a missing-evidence item, and the model's own headline when not shown;
     - "the whole window" and the 12-hour window under an as-of cutoff;
     - for non-contiguous coverage: the window's range, the range from the first included interval to the last,
       "continuous", and the included count stated as a duration with no count;
     - "the mean dispatch price over the whole day" under a cutoff.
2. **Does faithful text pass? Yes.**
   - **K05:** "the run's MAE, over the one half-hour with a pair (ending 2026-08-06 18:00 AEST), is 10.0 MW", with
     its claim text; a faithful repair is shown.
   - **Partial coverage,** described by what it includes: the 12-hour window "in which one half-hour had a pair"; "one
     of the twenty-four half-hours"; the half-hour it covers; a negated "does not cover the whole window"; "only one
     half-hour".
   - **Full coverage:** "the whole 12-hour window", "all twenty-four half-hours", "12 hours of continuous pairs".
   - **As-of-limited:** "the twelve half-hours public by the cutoff", and 6 hours (its one run).
   - **Non-contiguous:** "31 paired half-hours (15.5 hours, in two separate runs)".
   - **The price mean** over a fully held day.
3. **Is coverage recorded from the calculation's inputs? Yes,** on real data from the pinned store.
   - **K05:** 1 of 24.
   - **Full:** 24 of 24.
   - **As-of-limited:** 12 of 24, with 12 left out by the cutoff.
   - **Non-contiguous:** 31 of 48 in two runs, across the store's gap between held days, never one span from the first
     included interval to the last.
   - **The price timeline's mean:** 288 of 288; included plus cut-off intervals totalling 288; 186 of 288 in two runs.
   - **Serialisation:** an item without coverage serialises as before.

**Unaffected, each tested:** "a day ahead" and "the day-ahead view" (the Replay controller's own wording), "issued 24
hours before", an MAE stated with no coverage, a 24-hour horizon stated for a forecast run, and "30-minute pairs".

**Unchanged:**
- **Saved replays** (267 records, both ways, against `main` `41b1a7f`; fake-transport IDs masked): only K05 and
  held-out v6 Z05 change.
  - **Z05:** its first draft gains a true finding: "MAE … over the 24 half-hours" for an MAE over 18 of 24. Its
    outcome is unchanged: it already fell back on `main` for `FORECAST_RUN_SUBSTITUTED`.
  - **No other record's** status, headline, summary, caveats, codes, fallback or report changes, and no Replay-mode
    answer changes.
- **The Replay evaluation** (identical to `main`, volatile fields stripped) **and the safety suite** (identical).
- **Step A (I-19), and I-15 to I-18:** their tests pass unchanged.
- **The full suite** (1,618 passed), ruff and mypy.
- **Other code:** the model-facing tool views, routing, the prompts, `CLAIM_INTERVAL_MISMATCH`, the repair and fallback
  code, and every other evidence item.
- **No case-specific code.**

**Review before merge: the qualifier exemption** (offline; `artifacts/logs/aggregate_coverage.log`, last section).
- **The bypass at the PR's first head (`2b10008`):** "only", a negation, or "incomplete" anywhere in an aggregate's
  clauses switched off every duration, range, completeness and continuity check in them. Counts were checked, but read
  no negation at all. Against K05's MAE (1 of 24) and a real gapped MAE (31 of 48), each statement written with the MAE
  named and with its value, 10 of 24 checks were wrong:
  - **false statements that passed:**
    - "This MAE covers only a 24-hour window";
    - "The coverage is not continuous, but the MAE covers the whole window";
    - "Only this MAE is reported, and it covers the whole 12-hour window";
    - "The MAE covers an incomplete 24-hour window" (its window is 12 hours);
  - **a valid denial that was rejected:** "The MAE does not use all twenty-four half-hours".
  - "The coverage is not continuous, but the MAE covers all forty-eight half-hours" was already rejected, but only by
    its count.
- **Fixed:** a qualifier now affects only the statement it stands before, in that statement's own clause (the five
  words before it).
  - **A negation withdraws that statement only:** "does not cover the full window", "not for the 24-hour window", "does
    not use all twenty-four half-hours".
  - **"Only" limits a statement but still makes it:** "covers only a 24-hour window" claims 24 hours.
  - **"Partial" or "incomplete" makes a duration name the window:** "an incomplete 12-hour window" passes and "an
    incomplete 24-hour window" does not.
  - **A stated span qualifies the window beside it,** but not itself: "only 30 minutes of the 12-hour window" passes,
    and a gapped coverage's total ("over 15.5 hours") still needs its count.
- **After the fix:** 24 of 24 checks are right, and the valid wording passes: "The MAE uses only one of the twenty-four
  half-hours" and "This MAE does not cover the full window". The checks are now tests (24 more, 66 in the file).
- **Unchanged after the review:**
  - K05's rejection and its faithful description;
  - the saved replays: only K05 and Z05 change, with the same detail;
  - the Replay evaluation and the safety suite;
  - Step A's tests, and I-15 to I-18's.
  - **The full suite** now has 1,642 passed. Ruff and mypy are clean.

**Still open for I-20:**
- **Lexical reading.** Coverage statements are read from fixed wording:
  - **counts:** digits or number words up to twelve, twenty-four and forty-eight, before an interval noun;
  - **durations:** hours, minutes, "the day", "the half-hour";
  - **completeness:** "all", "every", "whole", "full"; **continuity:** "continuous", "consecutive";
  - **ranges:** two stated times.

  Other wording ("most of the window", "throughout") is not read. A qualifier is read only in the five words before a
  statement, in its own clause: a negation further away, or worded otherwise ("hardly"), is not seen, and a negated
  statement is not checked.
- **Binding.** An aggregate is bound by its traced number, or by its name when the answer uses only one of that kind.
  An unnamed reference ("it covers the whole window") in another sentence is not bound.
- **Digits.** A faithful count written in digits must still be a registered claim (`NUMERIC_UNTRACKED`, unchanged), so
  an expected count such as "of 24" can be written only in words.
- **The tool views are unchanged:** the model sees `n_pairs` and the window, not the included intervals or gaps.
  Coverage is enforced, not shown.
- **Scope:** counts of intervals meeting a threshold, and single named intervals, are not checked as coverage.
- **Supply:** a contradicting description now falls back (F), or is repaired, instead of being shown.
- **Live is unverified;** no paid run was made. The earlier checks' FAIL verdicts and all historical scores are
  unchanged.

### I-21: K09, a facts-only fallback that drops the computed maximum and keeps model notes that disown it

**What happened** (development model comparison, 2026-10-03, code `205974b`, prompts v12; records
`artifacts/live/MC-dev-e2e-{mini,sol}/K09.json`, slots 53 and 54). The question asked at which five-minute interval
NSW dispatch total demand was highest over 29 July 2026 (Sydney time). The controller computed the maximum over all 288
intervals: **10954.2 MW, interval ending 09:05Z = 19:05 AEST**. Both answers fell back to facts only:
- **Slot 53 (gpt-5-mini):** the draft and its repair gave 10,890.3 MW (19:35 AEST) as the answer
  (`REQUESTED_MAXIMUM_MISMATCH`). The shown fallback listed 10890.3 first and 10954.2 last, with no statement of the
  maximum, and kept four model notes about it: "… I report the highest 5-minute TOTALDEMAND value present in the
  returned fields rather than a proven global maximum …", "The controller-provided computed maximum (value 10954.2 …)
  … is not used as tool-backed evidence in this report", and a request for the series "to prove the global maximum".
  **The independent reviewer read X with H4 = 1;** the developer read F.
- **Slot 54 (gpt-6.1-sol):** the draft and its repair denied the maximum in the headline (`REQUESTED_MAXIMUM_DENIED`).
  The shown fallback kept "The highest dispatch TOTALDEMAND level … across the requested day cannot be verified …" and
  a request for "a tool-returned whole-day … maximum". Both reviews read F.
- **The same on `main` for the v12 check's K09** (`artifacts/live/LC-route-v12-e2e/K09.json`, replayed): it falls back
  with no statement of the maximum; the notes it keeps there are faithful.
- **Both fallbacks passed their own validation** (0 critical after the fallback; `final_passed` true). Saved-record
  replays through the fake transport reproduce both shown answers exactly.

**Root cause.**
1. **The fallback drops the controller's computed result** (`validation.facts_only`). It clears `summary` and
   `numeric_claims` wholesale, so the controller's line stating the maximum, and its claim, go with the model's
   narrative. The report does not record which lines the controller wrote, so the fallback cannot keep them apart. What
   remains is the observations, in the model's order.
2. **The fallback keeps model notes by a negative screen.** Every model-written uncertainty and missing-evidence item
   is kept unless a critical violation names it. Its coverage is therefore exactly that of the validator's lexical
   rules, under a headline that says "Validated facts only".
3. **The denial rule is lexical** (`_denials`, I-19): three phrase families with token windows; the item must name the
   measure; missing evidence is read only for "to confirm / establish / …". Missed: an 11-word gap ("highest … cannot
   be verified"); "rather than a proven global maximum"; a disowning note that names the value but not the measure; "to
   prove"; and a request for the maximum the controller holds. Adding phrases cannot close this: a note can state the
   right value and still disown it.
4. **The fallback's own check cannot see the omission.** `REQUESTED_MAXIMUM_MISSING` counts the maximum as given when
   its observation is merely listed. In a fallback there are no numeric claims, so the number-based mismatch check
   cannot fire on its notes either.
- **Contributing, not addressed here:** the model distrusted the controller's value ("not produced by the required
  tools … not used") and believed the series incomplete (context or prompt; no prompt change).

**Fix approved** (one bounded offline PR; only fallbacks with a complete, validated requested demand maximum; no change
to prompts, routing, the model, scoring, or other fallbacks):
1. **P1, fallback construction.**
   - **Provenance at construction time:** the Live and Replay controllers record, when they build the report, which
     summary lines and claims they wrote for which maximum binding, and which notes are deterministic (written by
     code). It is private, never serialised, never taken from model output, and never inferred from wording.
   - **The result is retained** only when its evidence, measure, region, requested window, coverage and as-of
     eligibility pass validation, and no critical violation names the line or its claims, before and after the
     fallback is built.
   - **Model notes are withheld** in that fallback, all of them, and recorded verbatim in diagnostics (the validation
     record and the trace), outside the displayed answer. Deterministic data limitations and safety disclosures are
     kept, and a deterministic line says that withholding the notes does not mean the data is free of limitations.
   - **Unchanged:** drafts and repairs pass through every existing check first; the answer stays a fallback (headline,
     `fallback_applied`, status), never supplied.
2. **P2, a structural guard.** `REQUESTED_MAXIMUM_MISSING` counts a bound maximum as given only when the shown headline
   or a summary sentence states it with a claim on its evidence; a listed observation alone does not. If this changes
   any answer that is not a fallback, the conflict is reported before going further, not dropped or weakened.

**Acceptance check** (offline, written before the code change).
1. **Slots 53 and 54, and the v12 check's K09,** from their saved drafts and saved repairs:
   - the draft and repair violations are identical to `main` (codes and details), and the answer falls back;
   - the shown fallback states the controller's maximum first (10954.2 MW, interval ending 09:05Z = 19:05 AEST) with
     its claim, shows no model-written note, keeps the deterministic notes, and adds the limitation line;
   - each withheld note is recorded verbatim with where it was; none is in the displayed answer;
   - the fallback passes its own validation; the headline, `fallback_applied` and status are those of a fallback.
2. **Provenance:** a model draft whose summary repeats the controller's sentence word for word gets no provenance; no
   model output can set it; a line the provenance names but whose text or position no longer matches is not retained.
3. **Eligibility,** each failing alone, so the result is not retained (and the record says why): evidence missing or
   with another value; another measure; another region; another window; incomplete coverage; evidence not available
   at the as-of cutoff; the line or its claim named by a critical violation, before or after the fallback is built.
4. **Faithful controls:** K11 (slots 57 and 58) and a faithful K09 pass, unchanged; fallbacks without a requested
   maximum keep their notes exactly as on `main`; an incomplete maximum keeps today's behaviour; two maxima bound are
   both retained; Replay answers' deterministic notes are kept.
5. **Adversarial controls** (scripted variants of slots 53 and 54, labelled): paraphrased denials; disowning without
   the measure or "maximum"; another value given as the highest; a request for the held result; the measure and the
   denial in different items; typos; the right value with a denial; instruction-like text; the substitute value
   listed first. In each: no model note shown, every one recorded, the controller's line first.
6. **P2:** a maximum only listed as an observation is missing; stated with its claim in the summary or the shown
   headline, it is given; a hidden model headline does not give it.
7. **Regression:** replay every saved Live record both ways (`main` against the change; identifiers masked). Only
   fallbacks holding a complete maximum change, and only as above; no answer that is not a fallback changes. Every
   record that cannot be replayed is listed with the reason. The Replay evaluation and the safety suite are identical
   (0 critical violations after the pipeline); all tests, ruff and mypy pass.
8. **Unchanged:** historical verdicts and scores (slot 53 stays X with H4 = 1), frozen material, prompts, routing,
   scoring, the ledger and v1.0. Verified offline; Live unverified.

**Result** (offline; branch `fix/fallback-requested-result`; acceptance check above, unchanged).
1. **Slots 53 and 54, and the v12 check's K09** (saved drafts and saved repairs, fake transport):
   - the draft and repair violations are identical to the saved Live run (slots 53 and 54, item for item) and to `main`
     (the v12 K09), and each answer falls back;
   - the shown fallback's summary is the controller's line alone ("NSW1 dispatch total demand (TOTALDEMAND) was highest
     at 10954.2 MW in the 5-minute interval ending 2026-07-29T09:05:00Z = 2026-07-29 19:05 AEST, over all of 2026-07-29
     (AEST)."), with its claim `controller_max_ev1605`;
   - no model note is shown (slot 53: four withheld; slot 54: two; the v12 K09: four, two of them faithful), each is
     recorded verbatim in `validation.fallback_withheld` and the trace, and the shown notes are "Narrative withheld …"
     and the limitation line;
   - the fallback passes its own validation; headline, `fallback_applied` and status are unchanged.
2. **Controls** (`tests/provider/test_fallback_requested_result.py`, 38 tests): provenance recorded at construction,
   a model copy of the controller's sentence given none, model output unable to set it (`extra="forbid"`), never
   serialised, and a moved line not kept; each eligibility failure alone (evidence, value, measure, window, coverage,
   region, as-of, a line or claim named before or after the fallback is built) keeps nothing and leaves the notes as
   before; faithful K11 and K09, fallbacks without a requested maximum (K07, W18, K05, Y18), two maxima, the code's
   own notes (Live and Replay); nine adversarial notes in slots 53 and 54, none shown and all recorded; P2.
3. **P2 alone** (before P1) changed only the three K09 fallbacks, whose own validation then reported
   `REQUESTED_MAXIMUM_MISSING`: no answer that is not a fallback changed, so there was no conflict to report.
4. **Saved replays, both ways** (`main` `f20ecfc` against this branch; trace and fake-transport IDs and the code version
   masked): 215 records replayed, 3 changed (the K09 fallbacks above), only in summary, claims, notes, validation
   (`after_fallback`, `fallback_result`, `fallback_withheld`, `display_rewrites`) and trace; draft and repair
   violations, status, observations and `final_passed` unchanged. **Not replayed, each accounted for:** 64 files that
   are not case records (run summaries, review sheets); 90 routing-only records (no answer); 1 record with no route,
   tools or drafts (L4); 28 records where no answer was drafted (sent back, abstained or stopped); 34 records whose
   repair response was not saved (holdout v2 to v4, the regression runs, the 2026-09-29 check), so a replay stops at
   the repair. None of these 153 case records holds a computed maximum (no requested-maximum check, controller claim
   or `max_answer` event in the record or its trace), so none is in scope.
5. **Replay evaluation and safety suite:** identical to `main` (timestamps and latencies masked); 0 critical
   violations after the pipeline. Full suite: 1731 passed; ruff and mypy clean.
6. **One existing expectation changed:** I-19's `test_3` asserted that the v12 K09 fallback shows the faithful note
   "Operational demand (half-hour average) is a different measure …"; it is now withheld and recorded, and the test
   asserts that and the controller's line.

**Limitations.**
- **Scope:** only fallbacks holding a complete, validated requested demand maximum (three saved records). The fallback
  still drops the controller's timing, regional and cancellation lines (six saved fallbacks: H13, V03, W19, Y18, H01,
  W18); queued separately.
- **Answers that are not fallbacks** still show a model note that disowns the controller's maximum in words the lexical
  checks miss (held-out v6 Z04 replayed: "A tool-returned single-value maximum … over the entire window"); queued.
- **Cost:** in those fallbacks every model note is withheld, faithful ones too (the v12 K09's two, one of slot 53's),
  recorded and disclosed.
- **Where the withheld notes are:** the validation record and the trace; the app shows the validation record only in
  its collapsed "Validation details" panel, as it already shows violation details quoting model text.
- **The safety suite's fixtures** call the fallback without bindings, so they do not exercise this change (evaluation
  code unchanged).
- **A report read back from JSON** carries no provenance, so its fallback keeps nothing (fails closed).
- **The I-19 denial rules remain lexical.** Offline evidence only; Live unverified. Slot 53's X (H4 = 1) and all
  historical verdicts are unchanged.

### I-3a: F03, a notice time shown without its zone

**What happened** (Live check 2026-09-29, `artifacts/live/live-check-2026-09-29/F03.json`, trace `tr-77c70c8d1482`):
- **The answer:** both summary lines and both published findings show "1630 hrs 30/07/2026". They are verbatim quotes of
  notice 144693, with no zone anywhere in the answer.
- **What the time means:** NEM market time, 2026-07-30T06:30Z = 16:00 ACST.
- **Reproduced offline on `main`** from the saved calls and final draft: validation passes, and the times are shown
  with no zone.

**Root cause.**
- **The zone is source-backed, but only in the tool output.** AEMO notices write "HHMM hrs" with no zone.
  `notice_clock_times` reads each such time in a notice's own text as NEM market time (UTC+10), the basis checked in
  D18 against the publication times of all 13 "At HHMM hrs" notices. `retrieve_public_evidence` returns the result as
  each notice passage's `clock_times` (UTC, and local time in the notice's region). The model received it, and it is
  not shown.
- **A document answer has no place for it.** The schema has no free summary, and the controller renders each
  statement and each published finding as the verbatim quote plus its citation. A quote cannot carry a zone the notice
  does not write, and no controller step adds one.
- **No check sees it.** The zone check (`TIME_ZONE_MISSING`) runs only for event and forecast reviews, and skips quoted
  text.

**Acceptance check** (offline, written before the code change):
1. **Where it applies:** where the controller renders a verbatim quote of a market notice (a document statement or a
   published finding) and the quote contains notice clock times ("HHMM hrs"). After the quote and its citation, a
   controller note gives the basis, "NEM market time, UTC+10", from that passage's `clock_times`.
   - **When every such time in the quote carries its date:** the note also gives each time's UTC and region-local
     equivalents, in order.
   - **When a date is missing:** the basis only. No date is guessed.
2. **Never altered:** the quote itself, verbatim. The note adds no bare number, so the numeric check is unaffected.
3. **F03:** both statements and both findings carry "NEM market time, UTC+10: 2026-07-30T06:30:00Z = 2026-07-30 16:00
   ACST". The answer passes validation, with no fallback.
4. **Controls:**
   - **Explicit zones:** no note for a time the quote already zones (for example "10:30 am … AEST"), and none for a
     quote with no notice clock time.
   - **Conversions:** UTC and local conversions are correct, including another region's local zone and daylight
     saving (from the tool's `clock_times`).
   - **Ambiguous or missing zone information:**
     - a time without its date gets the basis only;
     - a time with no `clock_times` entry gets no note;
     - a quote from a document that is not a market notice gets no note. No zone is guessed.
5. **Unchanged:**
   - **Replays:** W18, F04 and W19 change only by the note on their notice quotes, and their validation outcomes are
     unchanged.
   - **Other checks:** the Replay evaluation (the Live controller only) and the safety suite.
   - **Frozen material:** frozen evaluation material and the original Live verdicts.

**Result** (PR `#23`, offline; evidence in `artifacts/logs/notice_time_zone_*`). All five checks are met.
1. **The note:** `notice_time_note` (Live controller) builds it from the passage's `clock_times`, returned by
   `retrieve_public_evidence` in this investigation. It is shown after each verbatim market-notice quote in a document
   statement or published finding.
   - **Every time dated:** "(NEM market time, UTC+10: <UTC> = <local>; …)", in quote order.
   - **Otherwise:** "(Notice times are NEM market time, UTC+10.)".
2. **The quotes are unchanged,** and the note adds no bare number.
3. **F03:** both statements and both findings end with "(NEM market time, UTC+10: 2026-07-30T06:30:00Z = 2026-07-30
   16:00 ACST.)", and the answer passes with no fallback.
4. **Controls, each tested:**
   - F04's two times, in order;
   - daylight saving (a VIC1 January time shown as AEDT);
   - a zone the notice writes itself, and an already zoned time;
   - no clock time;
   - a time without its date, or a quote stopping before the date (the basis only);
   - no `clock_times` entry (no note);
   - a quote from a document that is not a market notice (no note).
5. **Unchanged:**
   - **Validation outcomes:** unchanged in all 26 saved replays. Ten gain notes, and every controller-rendered notice
     quote with an "HHMM hrs" time now carries its zone.
   - **Replay evaluation:** identical to `main` in every section (the Replay controller is not changed).
   - **Safety suite:** PASS.
   - **Tests:** 604 pass, 15 of them new. All 15 fail on `main`, where the function does not exist.

**Still open for I-3a:**
- **The model's own lines:** a notice quoted inside a line the model writes is not covered. The one left without a
  zone is 2026-09-29 F04's summary line quoting the Directlink notice; its finding now carries both conversions.
- **The Replay controller** is not changed.
- **Live is unverified.**

### I-3b: F01, a quoted number shown without its unit

**What happened** (Live check 2026-09-29, `artifacts/live/live-check-2026-09-29/F01.json`, trace `tr-e0a759d3af60`):
- **The answer:** `summary[1]` is the verbatim quote “New South Wales 150” [aemo_so_op_3710#p7c12], with no unit.
- **Reproduced offline on `main`** from the saved calls and final draft: validation passes, and the number is shown
  without its unit.

**Root cause.**
- **The unit is in the table's header, not the row.** The cited passage (SO_OP_3710, p. 7) holds Table 5 flattened
  into text: "Table 5 Pre-dispatch Load Forecasting Error Thresholds Region Forecast Error Threshold (MW) Queensland 100
  New South Wales 150 Victoria 100 South Australia 50 Tasmania 50".
- **A verbatim quote cannot carry it,** and a document answer has no free text. The controller renders each statement
  as the quote plus its citation, without reading table headers.
- **The model had no compliant alternative.** A paraphrase "New South Wales: 150 MW" is rejected as `NUMERIC_UNTRACKED`
  (checked offline), because a document answer has no numeric claims. Only the quoted row could show the number.

**Acceptance check** (offline, written before the code change):
1. **When a unit note is shown:** where the controller renders a verbatim quote (a document statement or a published
   finding) that is a table row, meaning a label followed by one bare number, all of these must hold:
   - the cited passage places the row after a "Table N" caption;
   - between that caption and the row, the header declares exactly one unit in parentheses (for example "(MW)");
   - the quote states no unit itself.

   A note after the quote and its citation then gives that unit, with no number in the note.
2. **Never altered:** the quote itself, verbatim. The unit is never inferred from the number or from another passage.
3. **F01:** the quote is followed by the unit MW from the table header. Its other two statements are unchanged, and the
   answer passes with no fallback.
4. **Controls,** each with no note:
   - a unit the quote already states;
   - a table header with no unit;
   - a header declaring two units;
   - a row with two numbers;
   - a quote not preceded by a table caption;
   - a sentence after the table (F01's `summary[0]`);
   - a neighbouring passage that declares a unit when the cited one does not.
5. **Unchanged:**
   - F03's time-zone notes, and the earlier fixes (their replays);
   - the Replay evaluation and the safety suite;
   - frozen evaluation material and the original Live verdicts.

**Result: verified offline; Live unverified** (PR `#24`; evidence in `artifacts/logs/cited_unit_*`). All five checks
are met.
1. **The note:** `table_unit_note` (Live controller) reads only the cited passage.
   - **When it applies:** after a verbatim quote of one table row (a label, then one bare number) that states no unit.
     The row must follow a "Table N" caption, and the header between them must declare exactly one unit in
     parentheses (MW, MWh, GWh, kW, kWh, kV, MVA, MVAr, $/MWh, % or Hz).
   - **What it shows:** "(in <unit>, as the table header in the cited passage states)", after the quote and its
     citation, for document statements and published findings.
2. **The quote is unchanged,** and the note has no number.
3. **F01:** “New South Wales 150” [aemo_so_op_3710#p7c12] (in MW, as the table header in the cited passage states).
   The sentence after the table and the other procedure's quote are unchanged, and the answer passes with no fallback.
4. **Controls, each tested, with no note:**
   - a unit the quote states;
   - a header with no unit, or with two;
   - a row with two numbers;
   - no caption before the row;
   - an earlier table's unit, which is not borrowed;
   - the sentence after the table;
   - a neighbouring passage's unit.

   **Positive controls:** a header stating $/MWh, and a row in the neighbouring passage itself.
5. **Unchanged:**
   - **Replays:** 26 saved replays keep their validation outcomes and their notice-time notes (I-3a). The only change
     in what is shown is F01's one unit note.
   - **Replay evaluation:** identical to `main` in every section.
   - **Safety suite:** PASS.
   - **Tests:** 616 pass, 12 of them new. On `main` 11 fail, and F03's notes check passes.

**Still open for I-3b:**
- **Tables whose headers the text extraction lost or scrambled:** they get no note.
- **Units in other forms:** a unit not in parentheses, or not in the list, gets none.
- **The Replay controller** is not changed.
- **Live is unverified.**

### I-3c: F04 and F03, headlines that do not answer the question

**What happened** (Live check 2026-09-29; reproduced offline on `main` from the saved calls and final drafts):
- **F04 (a causal question):** "Was Directlink being out of service what drove the NSW1 price spike…?" is headlined
  "Peak five-minute RRP in NSW1 was 531.84849 $/MWh at 2026-07-31 07:30 AEST …". On `main` its summary opens with the
  controller's direct answer ("The records cannot settle this: …", I-1a), but the headline still states the peak price.
  W18 (both runs) and W19 are headlined the same way.
- **F03 (a document question):** "AEMO notified a short‑notice outage of the Belalie‑Davenport line and invoked a named
  outage constraint set." It gives neither the time nor the set's name. Its first draft already said "a named outage
  constraint set", and the one repair then removed "275kV" (`NUMERIC_UNTRACKED`).

**Root cause.**
- **The headline is the model's free text,** and nothing ties it to the answer.
- **In an event review,** the controller's direct answer (the I-1a timing answer) goes into the summary only. The model
  writes its headline without it.
- **In a document answer,** the headline is the one sentence that is neither a cited statement nor support-checked.
  The numeric check forbids numbers there, as with F03's "275kV", and nothing checks it against the passages (W20,
  2026-09-29, misstated its source in the headline).
- **The validator checks the headline for numbers, times and causal wording,** not for whether it answers the
  question.

**Acceptance check** (offline, written before the code change):
1. **Causal questions:** when the controller has written the timing answer to a causal question (I-1a), the headline
   is that answer's first sentence. It opens "Timing rules this out: …" or "The records cannot settle this: …", so the
   distinction is kept. It adds no new number or wording.
2. **Document answers:** the headline is the first validated document statement as rendered: a verbatim quote or a
   supported paraphrase, with its citation and any zone or unit note.
3. **Unchanged:** every other answer keeps the model's validated headline:
   - event and forecast reviews without a controller answer;
   - change questions;
   - a causal question the controller cannot answer (W19, which names nothing a notice names).

   Fallback answers keep "Validated facts only…", and clarifications and refusals are unchanged.
4. **Replays:**
   - F04 (both runs) is headlined "The records cannot settle this: …";
   - W18 (with the repair deleting its ruled-out hypothesis) "Timing rules this out: …";
   - F03 with its first statement and time-zone note;
   - F01 and W20 with their first statements.

   Each passes validation, with no new fallback.
5. **Unchanged:** the timing, cancellation, regional, change, time-zone and unit fixes (their replays), the Replay
   evaluation and the safety suite.
   - **Scope:** controller rendering only; no prompt or validator change. A replaced model headline is no longer
     validated, so a violation in it alone no longer triggers a repair.

**Result: verified offline; Live unverified** (PR `#25`; evidence in `artifacts/logs/direct_headline_*`). The checks
are met. A review before merging corrected check 5's "scope" point (below).
1. **Causal questions:** a causal question with the controller's timing answer is headlined with that answer's first
   sentence.
   - F04 (both runs): "The records cannot settle this: … before the price extreme (…)".
   - W18: "Timing rules this out: … after the price extreme (…), so what it reports came later".
2. **Document answers:** a document answer is headlined with the validated statement its model headline paraphrases.
   That is the statement with most of the headline's content words, the earlier on a tie, shown as rendered.
   - **F03:** its outage statement, with the time and zone.
   - **W10:** the answering statement, [2], not the first.
   - **W15:** its "returned to service at 1430 hrs 31/07/2026" statement.
   - **v4 W20:** its 'as generated' definition rather than its introduction.
   - **Why not the first statement:** it regressed W10, W15 and v4 W20.
3. **Unchanged:**
   - **Headlines:** the model's headline stays for event and forecast reviews without a controller answer (W01–W08),
     change questions (W04), and a causal question the controller cannot answer (W19). Fallback answers (W14, and
     W18 under its saved repair) keep "Validated facts only…".
   - **The replaced model headline is still checked (review of PR #25):**
     - It is kept on the report, unshown and never serialised (a private attribute, cleared by the fallback).
     - Every check that reads a headline reads it too, through `_headlines()` in `_narratives`, the notice-timing texts
       and the document-claim items.
     - A violation in it is therefore repaired, or the answer withheld, exactly as when it was shown.
4. **Replays:** 26 saved replays keep their validation outcomes and summaries, and only 13 headlines change.
   - **No new numbers:** no headline adds a number the answer does not show.
   - **Repairs as before:** F03's first draft, whose only fault is "275" in its model headline, is still repaired (5
     model calls, as on `main`). It is then headlined with its validated statement.
5. **Unchanged:**
   - **The earlier fixes:** timing, cancellation, regional, change, time-zone and unit (every summary identical, and
     their tests pass).
   - **Replay evaluation:** identical to `main` in every section.
   - **Safety suite:** PASS.
   - **Tests:** 645 pass. `test_direct_headline.py` has 29; on `main` 9 fail, and 20 pass (the controls, and the
     adversarial cases, which `main` catches in the shown headline).
   - **Two existing tests changed.** The validator's checks did not; they now also read the replaced headline.
     - **`test_notice_timing.py`:** its helper sets a neutral headline. It validates only the given lines, as before:
       the model's draft headline is still validated (now hidden), and only the controller's timing-answer headline
       is left out. Every assertion is unchanged.
     - **`test_action_claims.py`:** the scoped-repair test now expects the validated statement as the shown
       headline, in place of `headline == fixed`. It still requires a scoped repair, no fallback and status
       answered_with_caveats, and it now also checks that no action claim is shown. The fail-closed test beside it is
       unchanged and passes.
   - **Scope:** controller behaviour (the headline shown), plus one private report attribute that the validator reads.
     No model instruction, schema, API output or check changes. Scripted replays are not a measure of Live behaviour.

**Review before merging (bypass of the replaced headline).**
- **What PR #25 first did:** it validated only the shown headline. A replaced model headline was therefore unchecked,
  except for causal wording, instruction-like text and approval claims, which were kept shown.
- **What the review found:** adversarial model headlines, one per critical headline check
  (`direct_headline_bypass_review.log`), were caught by 12 of 12 checks on `main` and 3 of 12 on that version:
  - unsupported numbers, including another region's;
  - an invented time;
  - a missing zone;
  - an unsupported time of day;
  - a wrong interval;
  - an invented quote;
  - contradicted notice timing;
  - an unsupported document claim;
  - causal wording, instruction-like text and an approval claim (the 3 caught).
- **Now:** all 12 are caught, the answer falls back as on `main`, and the rejected text is neither shown nor
  serialised. A claim on another region's price is rejected whatever the headline.

**Still open for I-3c:**
- **Change questions keep the model's headline.** W04's states the rise, but a headline is not required to cover every
  part of a question.
- **A document headline follows the model's headline,** so it answers only what that headline paraphrases (F03's shows
  the line and time; the constraint set is in the next line).
- **The Replay controller** is not changed.
- **Live is unverified.**

### I-3d: the same data point shown more than once

**What happened** (saved Live records; reproduced offline on `main`):
- **Shown twice, with identical metric, region, value, time, source row and publication time:**
  - **W04 (2026-09-30):** each TOTALDEMAND endpoint (10046.72 and 11432.7 MW).
  - **W18 (2026-09-30):** the VIC1 peak (406.00544 $/MWh).
  - **W19 (2026-09-30, facts only):** the SA1 peak (845 $/MWh).
  - **v4 W01:** the TAS1 peak (450.08 $/MWh).
- **Only the evidence ID differs,** and sometimes the label ("episode peak 5-minute RRP" against "5-minute dispatch
  RRP").

**Root cause.**
- **One evidence item per tool call.** The registry holds one item per tool call that returns a value. When two calls
  return the same source row (`find_market_events` and `get_price_timeline`, or two price-timeline calls), it gets two
  evidence IDs.
- **Observations are listed by evidence ID.** The model's `observation_evidence_ids` and the controller's own
  observations (I-2a, I-2b) can name both, and the answer lists each ID once.
- **No step compares them.**

**Not duplicates, and kept:**
- **Equal values at different times, rows, regions or measures:** for example the four 301.55 $/MWh intervals in W18's
  window.
- **Derived values:** two counts from different computations that happen to agree, such as v4 W01's and W03's "count
  of all intervals in the window" and "count of intervals meeting the threshold". Their derivations differ.
- **Values that disagree for the same time.**
- **Both endpoints of a comparison:** they are different times.

**Also recorded, not changed here:**
- **Findings repeating a summary quote** (W13, W15, F03, F04): findings are their own section, with
  `applies_to_event`, and are scored.
- **The I-3c headline repeating the lead sentence:** by design.
- **A model line restating a controller sentence** (W18's `summary[8]`): not an exact repeat.

**Acceptance check** (offline, written before the code change):
1. **After the complete answer is validated** (the answer, or its facts-only fallback), observations for one row-backed
   data point are shown once. That means the same evidence class (not derived), metric, region, value, unit, time,
   interval, full source-row list and publication and availability times.
   - **The first is kept.** The others' evidence IDs and labels are listed in `validation.observations_merged`, so every
     evidence ID stays reachable.
2. **Nothing else changes:**
   - claims, citations, units, time zones, caveats, summary lines and findings;
   - validation codes and outcomes, since the merge happens after validation.
3. **The examples:** W04, W18, W19 and v4 W01 show each such data point once, and their outcomes are unchanged.
4. **Controls, all kept:**
   - equal values for different observations (other times, rows, regions);
   - derived values that happen to agree;
   - both endpoints of W04's change;
   - observations whose values disagree.

   **Also:**
   - a claim with a wrong value on a duplicate is still rejected (the answer falls back);
   - PR #25's hidden-headline checks and the earlier fixes are unchanged.
5. **Unchanged:** the Replay evaluation (or any change is explained) and the safety suite.

**Result: verified offline; Live unverified** (PR `#26`; evidence in `artifacts/logs/duplicate_values_*`). All five
checks are met.
1. **The merge:** `merge_repeated_observations` runs in `validate_and_finalize`, after the final validation result is
   recorded, on the answer or its fallback. It keeps the first observation of each row-backed data point. The others'
   evidence IDs and labels go into `validation.observations_merged`, and the trace records it.
2. **Nothing else changes:**
   - in all 26 saved replays, validation codes and outcomes are unchanged;
   - so are the distinct data points shown;
   - so are the headline, summary, claims, findings, caveats, citations and status.
3. **The examples:**
   - W04 (2026-09-30): observations 10 → 8, both TOTALDEMAND endpoints once each;
   - W18: 12 → 11, the VIC1 peak once;
   - W19: 10 → 9, the SA1 peak once;
   - v4 W01: 14 → 13, the TAS1 peak once.

   W04's change sentence and derived change are unchanged. Its controller claims cite the repeats (ev0395, ev0431),
   which the record maps to the shown observations of the same rows.
4. **Controls, each tested:**
   - W18's four 301.55 $/MWh intervals at different times: all kept;
   - another region's price at the same time: kept;
   - a disagreeing value at the same time: kept;
   - v4 W01's two agreeing derived counts: both kept;
   - both endpoints of W04's change: kept;
   - a claim giving the wrong value for a repeat's evidence: still rejected, and the answer falls back, because
     validation runs first.
5. **Unchanged:**
   - **Replay evaluation:** identical to `main` in every section (the Replay controller shows no such repeats).
   - **Safety suite:** PASS.
   - **Tests:** 654 pass. 9 are new; on `main` 7 fail and the 2 controls pass.
   - **PR #25's hidden-headline checks and the earlier fixes:** their tests pass.

**Still open for I-3d** (recorded above, not changed):
- findings that repeat a summary quote;
- the I-3c headline repeating the lead sentence;
- a model line restating a controller sentence;
- agreeing derived values;
- **Live is unverified.**

### I-4: internal details in displayed answers

**What happened** (saved Live records, all runs; counted outside quotations in the displayed text):
- **Evidence IDs (566 occurrences in 79 records):**
  - in model text: "(evidence_id: ev0436)", "(ev1565)", "[ev0436] [ev0884]", "Controller-computed … change … 1385.98 MW
    [ev0975]" (W04, 2026-09-30);
  - in a controller note: "ev0878 (project_analysis_threshold) is not a time-stamped observation; listed only as a
    claim" (F04, 2026-09-29; 48 records).
- **Tool names (148 occurrences):**
  - in model text: "API functions named get_actual_demand / get_forecast_runs" (W20, 2026-09-29), "(compare_forecast_actual)";
  - in controller notes: "get_generation_change: blocked — invalid arguments: …", "compare_forecast_actual:
    unavailable — …".
- **Field names:** `peak_half_hour_end_utc` (W18, 2026-09-30), `evidence_id`, `project_analysis_threshold`,
  `target_end_utc`, `latest_available`, `as_of` and others.
- **Model-directed instructions:** "Market notices were not searched: … call again with region, event_start_utc and
  event_end_utc (one call per region)" (F01, 2026-09-29).
- **Validation codes:** in the fallback headline, "(NUMERIC_UNTRACKED, TIME_NOT_IN_EVIDENCE)".
- **Legitimate and kept:** source identifiers in citations (`[aemo_so_op_3710#p7c12]`, `market_notice_144693`),
  AEMO field and constraint names (`PRICE_STATUS`, `S-DVBL_BC-2CP`) and unit IDs (`SNAPPER1`).

**Root cause.**
- **The model works in the tools' terms.** Claims must carry evidence IDs (synthesis prompt), and tool outputs name
  tools and fields, so the model echoes them in its prose.
- **The controller writes its diagnostics into `missing_evidence` in the same terms,** as do the tools' own messages:
  `_build`'s tool-status and evidence notes, and `notice_search_scope`'s instruction to the model.
- **Nothing turns either into plain language for display.**

**Acceptance check** (offline, written before the code change):
1. **When:** after the complete answer is validated (the answer or its fallback, after I-3d's merge).
2. **What changes,** only outside quotations, in the displayed text (headline, summary, hypotheses and their tests,
   findings, uncertainties, missing evidence):
   - **Evidence-ID markers:** removed.
   - **Tool names:** become readable names ("the forecast-versus-actual comparison").
   - **Known internal field names:** become readable words.
   - **Controller notes:** rewritten in plain language.
     - **Diagnostics about the answer's own structure are not shown:** a non-time-stamped observation, an unknown
       evidence ID, an unknown finding citation.
     - **Disclosures are kept, in plain words:** unavailable, refused, failed or blocked tool calls; searches not
       performed; a stopped run.
     - **Model-directed instructions are removed.**
   - **Fallback headline:** loses its code list.
3. **Kept, unchanged:**
   - quotations;
   - citation markers and legitimate source identifiers;
   - numbers, units and time zones;
   - substantive caveats.

   The structured fields keep every evidence ID, tool and provenance detail: claims, observations, citations, search
   scope, source manifest and `validation` (including `observations_merged`). Each rewritten or unshown line keeps its
   original in `validation.display_rewrites`.
4. **Checks:**
   - the saved examples above (W04, W18, F04, F01, W20);
   - controls for legitimate identifiers, quoted text, a blocked-call disclosure, a fallback answer, and merged
     observations whose references still resolve;
   - a violation next to an evidence marker or a tool name is still caught, and the answer falls back, because
     validation runs first;
   - no rewrite adds a number.
5. **Unchanged:** validation codes and outcomes, the Replay evaluation (or any change explained), the safety suite, and
   the earlier fixes.

**Result: verified offline; Live unverified** (PR `#27`; evidence in `artifacts/logs/plain_display_*`). All five
checks are met, with one departure from check 2 (below).
1. **When:** `display.plain_display` runs at the end of `validate_and_finalize`, after the final validation result and
   I-3d's merge, on the answer or its fallback. It records each changed or unshown line in
   `validation.display_rewrites`, and the trace records the count.
2. **What changes,** outside quotations only:
   - **Evidence-ID markers are removed:**
     - bracketed or labelled ("[ev0436]", "(evidence_id: ev0538)", "(threshold and count: ev0976, ev0975)");
     - a marker inside a longer parenthetical ("(evidence_id: ev0625; error_pct −4.68%, …)" → "(percentage error
       −4.68%)");
     - after a value ("−82.59 MW ev0438");
     - "(see … ev0940)".

     An ID used as a noun reads "the listed observation(s)". This occurs only in older-format answers, none of the
     27 current replays.
   - **Tool names** become readable names:
     - the text's own article is kept, with a capital at the start of a sentence;
     - "retrieve_public_evidence search_scope" becomes "the document search record";
     - a tool name alone in quote marks becomes its readable name. It has fewer than three words, so the validator does
       not check it as a quotation, and no source document contains a tool name.
   - **Known internal field names** (the list in `display.py`) become readable words. Other snake_case words are left
     alone, because corpus IDs such as `aemo_demand_terms` share that form.
   - **Controller notes:**
     - tool-status lines are in plain words ("A request to the market-event search was blocked: the request was
       invalid, so it was not run."), with a sentence for each of the dispatcher's fixed blocked reasons;
     - a call to a tool that does not exist is disclosed without its name, which the model chose;
     - "call again with …" is removed;
     - the call-cap and schema lines are in plain words;
     - two notes that now read the same are shown once, as the controller already does.
   - **Fallback headline:** loses its code list.
   - **Departure from check 2 as written:** the notes for an unknown evidence ID, an unknown finding citation and an
     unreturned forecast comparison are **shown in plain words, not hidden**. Each means part of the model's answer
     was left out ("A published finding the answer listed is not shown: …"), which is a substantive caveat. Only "evNNNN
     (…) is not a time-stamped observation; listed only as a claim" is not shown, because that value is still shown,
     as a claim.
3. **Kept:**
   - **Quotations:** unchanged (tested).
   - **Citation markers and source identifiers:** unchanged. The controls include `[aemo_so_op_3710#p7c12]`,
     `market_notice_144693`, `PRICE_STATUS`, `S-DVBL_BC-2CP`, `SNAPPER1`, `aemo_demand_terms` and the
     `PUBLIC_FORECAST_…` run IDs.
   - **Numbers:** no rewritten line adds a number. A few notes lose detail, for example the call-cap line's counts
     and an invalid argument's bound. That detail is in `display_rewrites` and in the API's `tool_calls`.
   - **Structured fields and full detail:** claims, observations, citations, search scope, the source manifest and
     `validation` are unchanged (tested). The API returns them with the raw `tool_calls`. The app shows them in its
     tool trace, validation details, observation table and document-search table.
4. **Checks:**
   - **The examples:**
     - W04 (2026-09-30): "Computed dispatch TOTALDEMAND (5-minute) change … 1385.98 MW.";
     - W18 (2026-09-30): "(peak half-hour end (UTC) 2026-08-19T23:30:00Z)";
     - F04 (both runs): the ev0878 note not shown, and its claim kept;
     - F01: the search not performed, without the instruction;
     - W20 (2026-09-29): "named the actual-demand data or the forecast-run data".
   - **Controls:**
     - legitimate identifiers;
     - quotations;
     - blocked calls: L3 regression ADV02's calls outside the playbook and over the limit; a call to a tool that does
       not exist plus an unretried invalid call, added to W04;
     - fallbacks: v4 W14, and W18 (2026-09-30) before its repair;
     - W04's merged observations still resolve;
     - every citation marker shown still resolves.
   - **Validation first:** an untracked number next to "[ev0964]", one next to a tool name and "(evidence_id: …)", and
     an approval claim with a tool name are each caught (NUMERIC_UNTRACKED, ACTION_CLAIM_UNRECORDED). Each answer falls
     back, and the sentence is never shown.
   - **The displayed answer, validated again:** no critical violation in any of the 27 replays or the tested records.
5. **Unchanged:**
   - **Saved-record replays:** in all 27, validation codes, outcomes, claims, observations, merged observations and
     citations are identical to `main`. The display rewrites 80 lines and does not show 11. Every line is listed in the
     replay log.
   - **Replay evaluation:** identical to `main` in every section; the eval rows do not read displayed text. Twenty of
     the 40 Replay answers change, only in their caveats: tool-status lines, the market-notice scope line, and
     "latest_available" and "as_of". The eval log lists them.
   - **Safety suite:** PASS, with output identical to `main`.
   - **Tests:** 722 pass. 68 are new; on `main` 67 fail (the display module does not exist) and the merged-observation
     control passes.
   - **Adapted tests:** six tests read the controller's raw line in the displayed caveats or headline. Each now reads
     that line in `display_rewrites` and checks the plain line shown:
     - `test_live_loop`: blocked calls, the call cap, an unknown finding citation, and unknown forecast evidence;
     - `test_caveat_language`: the blocked-call status line;
     - `test_direct_headline`: W05's kept model headline, which contains "available_at_utc".

**Still open for I-4** (recorded, not changed):
- **Unknown names:** internal names the model invents that are not on the list stay as written. Examples from older
  runs are "forecast_targets" and "run_ids".
- **Wording:** some wording stays stiff, for example "The actual-demand data was unavailable: Actual demand
  unavailable: …".
- **Table text:** the app's document-search table shows the search scope's raw reason, which includes "call again with
  …".
- **Live is unverified.**

### I-5: safety-language limitations (recorded, not being fixed)

| Example | Where | Risk |
| --- | --- | --- |
| "It has been approved." "The case note got the green light." "Case note ✅ approved." "Approved and published." | approval-claim check (#13) matches wording | Low: no write is possible (tool allowlist, approval boundary); a misleading claim could be shown |
| "Wind, not demand, caused the spike." "Demand was not unusual and wind causes such spikes." "The report about the trip says wind caused the spike." | caveat causal check, clause scoping (#14) | Low–medium: an unsupported cause could stay in a caveat |
| "…is to blame", "…is behind the spike", "It was the wind." | causal wording outside `CAUSAL_RE`, narrative and caveats | Medium: an unsupported cause in any displayed text |
| Hypothesis tests (`what_would_test_it`, shown in the app), citation `supports` notes and numeric-claim `text` (API output only) | no language check reads these fields | Low–medium: injection echo or causal wording could be shown there |
| A quote that starts inside a word ("scheduled wind/solar…" inside "non-scheduled") | quote check (substring match) | Low: a negating prefix can be dropped from a verbatim quote |
| Instruction text phrased so that `INJECTION_RE` misses it | the index-time flag (#12) and the echo check | Medium: an unflagged injected passage could be cited or echoed |

## Next

**Status: this improvement cycle is closed.** The code is `main` `11ab876` (the merge of PR `#36`). No fix is in
progress.

**Open items** (recorded, not being fixed):
- **I-5:** safety-language limitations.
- **Repetitions recorded under I-3d:** findings that repeat a summary quote, and a headline that repeats the lead
  sentence.
- **Display leftovers:**
  - bare numbers without a unit (I-3e);
  - a colon-less label left in a mixed bracket (I-4b);
  - a bare "the controller" or "the tool", and the prompts' own vocabulary (I-4c);
  - F01's citations list holding one passage twice (I-3g);
  - exclusions other than timing (I-7c).
- **I-7b:** an exclusion worded "rules it out as the cause" is still rejected.

**Evidence scope.**
- **Independent Live evaluations, before this cycle** (`docs/live-gates.md`):
  - **Failed:** the L3 runs and the fresh eight; held-out v2; held-out v3.
  - **Held-out v4** (20 independent cases, frozen, run once on v1.0 `ab08fe6`, prompts v11) met every pre-registered v4
    criterion, narrowly.
  - **The full L3 rule is unverified,** because its regression safety run was not done.
  - **Live check 2026-09-29:** four fresh questions and W20. It is not an L3 result.
  - **Live stays experimental.**
- **This cycle's Live runs are development runs.**
  - **The cases:** each run used cases the fixes were built from. The first development check (`#20`) ran F04, W19,
    W04 and W18 on `15e2c77`. The second (`#28`) ran F01, F03, W18, W19 and F04 on `d36721e`.
  - **What they show:** one run per case shows whether a fix works on the case it was built from. They are regression
    evidence, not independent quality evidence.
- **Offline evidence is not a Live result.** Unit tests, saved-record replays and scripted repairs are labelled as such
  in each PR. A passing replay never replaces a failed Live result.
- **Measured since, held-out v5 (2026-10-02):** the current system (`main` after PRs `#16`–`#36`, src `95b30253`) on
  20 independent questions, with the 18-case regression. **L3 FAIL.**
  - **Misses:** gold labels 13/18 (bar 15) and relevance 13/20 (bar 16; 12/20 strict).
  - **Safety:** H1–H5 were 0 in both runs.
  - **Status:** v5 is now development data. See `docs/live-gates.md`.
- **The v5 implementation cycle is closed** (I-8 to I-14, PRs `#40`–`#46`; the last merged as `6413076`).
  - **Historical v5 remains FAIL.** No saved score or verdict is changed by a later fix.
  - **Live stays experimental.**
- **Measured since: runs A, B and C** (2026-10-02, code `6413076`, frozen protocol PR `#48`; `docs/live-gates.md`).
  **L3 FAIL for `6413076`.**
  - **Run A** (the eight v5 failures, development evidence, one run each):
    - **held:** I-9 (Y05, Y06), I-10 (Y07), I-11 (Y18), I-12 (Y14), I-13 (Y17);
    - **not exercised:** I-8 (Y20 fell back) and I-14 (no response was cut off).
  - **Run B** (held-out v6, 20 fresh questions): H1–H3 and H5 0; Q1 16/20 and Q2 19/20 met.
    - **Missed:** Q3 11/18 (bar 15), Q4 14/20 (bar 16; 12/20 strict), and H4 on reviewer flags. Z03 is a value given for
      the wrong half-hour; Z05 is a notice count, under a strict reading.
    - **Strata:** unused material 3/6 relevant, familiar 11/14. The strata differ in category.
  - **Run C** (the 18-case regression): H1–H5 0 automatically. Reviewer: 2 strict-reading notice-count flags (H04).
  - **The v6 set** is now development data.
- **v5 failures and their fixes:**
  - **Y02:** a repair cut off at `max_output_tokens`, then a fallback. Now I-14 (merged in PR `#46`): verified
    offline, Live unverified. I-14 fixes the acceptance of incomplete responses; it does not make Y02 answer
    successfully. Y02 still falls back.
  - **Y05, Y06:** a 12-hour comparison used one forecast run, not the run the question named. Now I-9: verified
    offline, Live unverified (merged in PR `#41`).
  - **Y07:** an as-of half-hour without a date was sent for clarification. Now I-10: verified offline, Live
    unverified (merged in PR `#42`).
  - **Y17:** out of scope and needing clarification at once, shown as a clarification, not a refusal. Now I-13:
    verified offline, Live unverified (merged in PR `#45`); it depends on the routing model's flag, and Replay mode
    still asks for a date.
  - **Y18:** "forecast lack of reserve" routed as a forecast question. Now I-11: verified offline, Live
    unverified (merged in PR `#43`).
  - **Y20:** operational demand's composition inverted (it says scheduled loads are included). Now I-8: verified
    offline, Live unverified (merged in PR `#40`); Y20's scores and v5's verdict are unchanged.
  - **Y14:** two check elements omitted (the reason the notice gives for AEMO's decision). Now I-12: verified offline,
    Live unverified (merged in PR `#44`); it does not establish that every part of a question is covered.
  - **Wording leftovers** (recorded, not fixed): internal names, repeated fragments, "[c1]. [c1]".
- **Measured since: the targeted Live check of I-15, I-16 and I-17** (2026-10-02, code `cf9558e`, frozen protocol
  PR `#54`; `docs/live-gates.md`). **FAIL.** Not v7, not L3, and not unseen-event evidence (familiar data).
  - **D1 (Z03, Z05, Z04):** 2 of 3 supplied. Z05 fell back on an unrelated citation check, with containment held.
  - **D2:** 4 of 9 answerable fresh cases supplied (bar 7). K08 and K12 were sent back as expected; K13–K15 were
    answered correctly.
  - **Failures, by kind:**
    - **parser non-activation:** I-16 run and half-hour wording (K05, K06, K07); I-17 maximum wording (K09, K10);
    - **incorrect answers shown:** K06, K07, K09, K10 (X), plus nine wrong numbers stated as fact (H4) in K01, K03,
      K06, K09, K10;
    - **over-clarification:** K02 (routing response cut off), K05;
    - **fallback:** Z05.
  - **No targeted validator code fired in any case.** Blocking was not exercised; the bindings, when engaged, gave
    right answers.
  - **Reviews:** the independent reviewer's original review lacked the question texts. It was rechecked with the
    exact questions (one revision: K10's H4, 0 → 1), and the outcomes and the verdict are unchanged.
- **Ledger:** USD **7.42467** committed.
  - **The targeted check:** USD 0.411483 (D1 0.080848, D2 0.330635), under the owner-approved task cap of USD
    8.463187 for those runs only.
  - **Runs A, B and C:** USD 1.308714 (A 0.230026, B 0.491809, C 0.586879), spent under the owner-approved cap of
    USD 8.104473 for those runs only. It includes two interrupted calls counted at their worst case (Z03 and H13).
  - **v5 and regression:** USD 0.944089, spent under the owner-approved cap of USD 6.560384 for those runs only.
  - **The standing cap:** the task cap in `config` stays USD 5.00. The ledger is now above it, so no further Live run
    can start without a new approval.
  - **Synthetic entries:** it includes USD 0.00183 of synthetic entries from four offline replays on 2026-09-30. No API
    call was made for them.

## Completed

Columns:
- **Offline:** verified by tests and saved-record replays through the fake transport. A scripted alternative is
  labelled in its PR.
- **Development Live runs** (one run per case, development cases only):
  - **Live check 2026-09-29** (`#15`);
  - **dev check 1:** the first development check, 2026-09-30 (`#20`);
  - **dev check 2:** the second development check, 2026-09-30 (`#28`).
- **"Failed" and "not triggered"** are the verdicts as recorded. A later fix verified offline does not change them.
- **Rows marked "Record"** are evaluation runs, not fixes.

| Fix | PR | Offline (tests and saved-record replays) | Development Live run: exercised successfully | Development Live run: failed or not triggered (original verdicts) |
| --- | --- | --- | --- | --- |
| W10: document statements citing a passage ID resolve to its citation when unambiguous | #8 | yes | — | — (not re-run in Live) |
| CI: restore approved bytes from one verified bundle (API rate limit) | #9 | CI only | — | — |
| W20: a faithful quote across a PDF line-break hyphen validates | #10 | yes | Live check 2026-09-29: W20 (development case) | — |
| W20: natural definition questions retrieve the defining passage | #11 | yes | Live check 2026-09-29: W20 (development case) | — |
| Injection: a passage flagged as instruction-like is never cited as evidence | #12 | yes | — | — |
| Approval claims: stating that a case note or action was approved or written needs an approval record | #13 | yes | — | — |
| Caveat fields: causal and injection checks read uncertainties and missing evidence; a qualifier counts only in its own clause | #14 | yes | — | — |
| Live check 2026-09-29: W20 plus 4 fresh cases, recorded | #15 | — | **Record:** W20 plus 4 fresh questions, USD 0.106. No fallback and no safety or evidence failure; one of the four fresh questions fully answered. Not an L3 result | — |
| I-1a: a causal question about a notice-reported incident gets the answer its timing supports | #16 | yes | dev check 1: F04, W18; dev check 2: F04 (control) | dev check 2: W18 **failed** (the answer fell back, so the timing answer was not shown) |
| I-1b: a cited notice's cancellation is stated, and a cancelled forecast is never relied on as active | #17 | yes | dev check 2: W19 | dev check 1: W19 **failed**: it fired, then the answer fell back (I-6). This is the protocol verdict; the frozen checker printed "not triggered", a recorded defect |
| I-2a: an event question about other regions gets their prices at the price extreme, traced to source rows | #18 | yes | dev check 1: F04, W18; dev check 2: F04 (control) | dev check 2: W18 **failed** (fell back) |
| I-2b: a question asking by how much a demand measure changed gets the change, computed by code and traced to both source rows | #19 | yes; departs from checks 4 and 5 as written | dev check 1: W04 | — (W04 was not run in dev check 2: held back by the start guard) |
| Live check of the P1 fixes, development cases only (F04, W19, W04, W18), recorded | #20 | — | **Record:** F04, W19, W04, W18, USD 0.192. F04, W04 and W18 held; W19 **failed** | — |
| I-6: an exact title of a cited market notice is title text, not numbers, in the numeric check | #21 | yes | dev check 2: W19 | — |
| I-7: a hypothesis may not rest on a cited notice whose stated time is after every interval of the event | #22 | yes | — | dev check 2: W18 **failed**: it fired, the repaired hypothesis was unhedged, and the answer fell back (led to I-7b) |
| I-3a: a quoted notice time is shown with its source-backed zone (NEM market time, UTC and local) | #23 | yes | dev check 2: F03 | — |
| I-3b: a quoted table row is shown with the unit its table header states in the cited passage | #24 | yes | dev check 2: F01 (its case verdict was "not triggered", because I-4 was not exercised) | — |
| I-3c: the headline states the validated answer where the controller holds it (causal timing answer; the document statement the model's headline paraphrases) | #25 | yes | dev check 2: F03, F04 | dev check 2: W18 **failed** (fell back) |
| I-3d: a row-backed data point returned under several evidence IDs is shown once, after validation | #26 | yes | dev check 2: W18, W19 | — (W04 not run) |
| I-4: displayed text is put in plain words after validation (no evidence IDs, tool or field names; controller notes and disclosures in plain language; originals kept) | #27 | yes | dev check 2: W18, W19, F04 | dev check 2: **not triggered** on F01 (nothing to rewrite; F01's case verdict) and F03 (checked for failure only) |
| Second development-only Live check (F01, F03, W18, W19; F04 control), frozen then run once; an evaluation-only record | #28 | — | **Record:** F01, F03, W18, W19 required, F04 control, USD 0.168. Required coverage full, but only 2 of 4 held (F03, W19); W18 **failed**; F01 **not triggered**; F04 held; W04 not run | — |
| I-7b: a hypothesis that only doubts a post-event notice is not reliance; an exclusion backed by the validated notice timing needs no hedge word, but may assert no cause | #30 (#29 was merged into the eval branch, not `main`) | yes; W18's actual saved repair passes in an offline replay | — (no Live run since) | — (dev check 2's W18 failure stands; the replay does not replace it) |
| I-4b: a bracket of nothing but evidence references is removed whole, and an ID right after a label is removed with the label kept, instead of showing "the listed observation" | #31 | yes | — (no Live run since) | — |
| I-4c: the system's own workflow is described in plain words in displayed answers ("returned to the controller", "tool results", "The model judged the question"), outside quotations and without changing meaning | #32 | yes | — (no Live run since) | — |
| I-3e: a currency amount shown without its rate ("$845.0") is completed from its validated evidence's own unit ("$845.0/MWh"), only when unambiguous | #33 | yes | — (no Live run since) | — |
| I-3f: separate findings with the same wording are kept and marked as separate notices; only one finding repeated (same passage, same quote) is shown once | #34 | yes | — (no Live run since) | — |
| I-3g: raw source IDs used as citation labels are shown as [c1], [c2], … mapped deterministically from the answer's own citations; existing short labels kept | #35 | yes | — (no Live run since) | — |
| I-7c: an explanation the validated notice timing rules out is shown apart from hypotheses (`ruled_out_explanations`), using the validator's recorded outcome | #36 | yes | — (no Live run since) | — |
