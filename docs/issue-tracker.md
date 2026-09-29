# Issue tracker: Live answer defects

One list of known defects, so that each fix is weighed against the whole. Evidence comes from saved Live records
(`artifacts/live/`) unless a row says otherwise.
- **Priority:** P1 means the user's question goes unanswered or answered wrongly; P2 means the answer is right but hard
  to read or trust; P3 is a known, bounded limitation.
- **Paid checks:** a paid Live check runs after a meaningful group of fixes, not after each PR. Until then a fix is
  verified offline only.

## Open

| ID | Area | Concrete example | Priority | Status |
| --- | --- | --- | --- | --- |
| I-1 | **Direct, complete answers** | **(a)** F04 (live check 2026-09-29) asked "Was Directlink being out of service what drove the NSW1 price spike…?": the answer lists correct observations and hedged possibilities but never says what the evidence supports. **(b)** W19 (held-out v4) does not say the reserve (LOR) forecasts were cancelled before the day, and its hypotheses lean on them | P1 | **(a): fixed offline** in PR `#16` (below), **Live unverified**. **(b): fixed offline** in PR `#17` (below), **Live unverified** |
| I-2 | **Evidence selection and calculations** | **(a)** F04 never fetched the other regions' prices, so it misses that VIC1, SA1 and TAS1 were also above 470 $/MWh while QLD1 was about 65. **(b)** W04 gives both total-demand values (10046.72 and 11432.7 MW) but not the rise between them: a derived number has no evidence ID | P1 | open |
| I-3 | **Clear presentation** | F01 shows "New South Wales 150" without "MW". F03 shows "1630 hrs" without its zone (NEM time, 06:30 UTC). Headlines are vague or off the question: F03's after repair, F04's (the peak price) | P2 | open |
| I-4 | **Internal details in user-facing text** | Tool names (W20: "API functions named get_actual_demand / get_forecast_runs"), controller notes ("Market notices were not searched…" on document questions, F01), and evidence IDs (F04: "ev0878 … is not a time-stamped observation") | P2 | open |
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

**I-2 (evidence selection and calculations).** P1. **I-2a:** F04 never fetched the other regions' prices. **I-2b:** W04
leaves the rise between two demand values implicit. I-1 (direct answers) is fixed offline for its two recorded
examples; both fixes await the next paid Live check.

## Completed

| Fix | PR | Verified |
| --- | --- | --- |
| W10: document statements citing a passage ID resolve to its citation when unambiguous | #8 | offline; not re-run in Live |
| CI: restore approved bytes from one verified bundle (API rate limit) | #9 | CI |
| W20: a faithful quote across a PDF line-break hyphen validates | #10 | offline; Live check 2026-09-29 (development case) |
| W20: natural definition questions retrieve the defining passage | #11 | offline; Live check 2026-09-29 (development case) |
| Injection: a passage flagged as instruction-like is never cited as evidence | #12 | offline |
| Approval claims: stating that a case note or action was approved or written needs an approval record | #13 | offline |
| Caveat fields: causal and injection checks read uncertainties and missing evidence; a qualifier counts only in its own clause | #14 | offline |
| Live check 2026-09-29: W20 plus 4 fresh cases, recorded | #15 | Live, USD 0.106 |
| I-1a: a causal question about a notice-reported incident gets the answer its timing supports | #16 | offline; **Live unverified** |
| I-1b: a cited notice's cancellation is stated, and a cancelled forecast is never relied on as active | #17 | offline; **Live unverified** |
