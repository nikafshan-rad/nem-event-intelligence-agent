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
| I-8 | **A definition shown with its meaning reversed** | Y20 (held-out v5, Live, 2026-10-02): asked whether operational demand counts scheduled loads, the answer said it *includes* "local demand of scheduled loads and scheduled bidirectional units" [c1], citing figure text that subtracts them; the definition excludes them. It passed validation and was shown | P1 | **verified offline; Live unverified** (PR `#40`, below). v5's FAIL verdict and Y20's scores are unchanged |
| I-9 | **The forecast run asked for, replaced by another** | Y05, Y06 (held-out v5, Live, 2026-10-02): asked for the last forecast issued before a named half-hour, both answers gave a run issued about three hours earlier (Y05 POE50 10,972 MW from the 17:56:59Z run instead of 11,082 from the 20:56:59Z run; Y06 2,017 from 04:27:00Z instead of 1,816 from 07:26:58Z), presented as the run asked for | P1 | **verified offline; Live unverified** (PR `#41`, below). v5's FAIL verdict and Y05/Y06's scores are unchanged |
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
   - **Tests:** the full suite passes (1,080, of which 28 are new).
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
- **Window figures are not bound.** MAE and mean error over a wider window have no source rows; only values for the
  half-hour asked about are bound.
- **Evaluation scoring:** the controller's comparison counts as the required tool executed.
- **Live is unverified;** no paid run was made.

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
- **Observed in v5** (recorded, not being fixed):
  - **Y02:** a repair cut off at `max_output_tokens`, then a fallback.
  - **Y05, Y06:** a 12-hour comparison used one forecast run, not the run the question named.
  - **Y07:** an as-of half-hour without a date was sent for clarification.
  - **Y17:** out of scope and needing clarification at once, shown as a clarification, not a refusal.
  - **Y18:** "forecast lack of reserve" routed as a forecast question.
  - **Y20:** operational demand's composition inverted (it says scheduled loads are included). Now I-8: verified
    offline, Live unverified; Y20's scores and v5's verdict are unchanged.
  - **Y14:** two check elements omitted.
  - **Wording leftovers:** internal names, repeated fragments, "[c1]. [c1]".
- **Ledger:** USD 5.704473 committed.
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
