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
| I-1 | **Direct, complete answers** | **(a)** F04 (live check 2026-09-29) asked "Was Directlink being out of service what drove the NSW1 price spike…?": the answer lists correct observations and hedged possibilities but never says what the evidence supports. **(b)** W19 (held-out v4) does not say the reserve (LOR) forecasts were cancelled before the day, and its hypotheses lean on them | P1 | **(a): fixed offline** in PR `#16`. **Live (development cases only, 2026-09-30): held** on F04 and W18. **(b): fixed offline** in PR `#17`. **Live (development case): failed** on W19: it triggered internally and the sentence was correct, but the answer fell back, so it was not displayed (I-6). The outcome stays failed |
| I-2 | **Evidence selection and calculations** | **(a)** F04 never fetched the other regions' prices, so it misses that VIC1, SA1 and TAS1 were also above 470 $/MWh while QLD1 was about 65. **(b)** W04 gives both total-demand values (10046.72 and 11432.7 MW) but not the rise between them: a derived number has no evidence ID | P1 | **(a): fixed offline** in PR `#18`. **Live (development cases only, 2026-09-30): held** on F04 and W18. **(b): fixed offline** in PR `#19`; departs from checks 4 and 5 as written (below). **Live (development case): held** on W04 |
| I-3 | **Clear presentation** | F01 shows "New South Wales 150" without "MW". F03 shows "1630 hrs" without its zone (NEM time, 06:30 UTC). Headlines are vague or off the question: F03's after repair, F04's (the peak price). W04 and W18 (Live, 2026-09-30): the same value appears twice among the observations, and W04's headline has "(UTC+1000)". (W18's inconsistency is now I-7) | P2 | open |
| I-4 | **Internal details in user-facing text** | Tool names (W20: "API functions named get_actual_demand / get_forecast_runs"), controller notes ("Market notices were not searched…" on document questions, F01), and evidence IDs (F04: "ev0878 … is not a time-stamped observation"). W04 (Live, 2026-09-30): "Controller-computed dispatch TOTALDEMAND (5-minute) change … [ev0975]" | P2 | open |
| I-6 | **A valid controller answer lost to a fallback** | W19 (Live, 2026-09-30): the controller's cancellation sentence was correct, but the model's own lines quoted notice titles in single quotes ('… Lack Of Reserve Level 2 (LOR2) …'). `NUMERIC_UNTRACKED` counted the "2", and one line failed `TIME_NOT_IN_EVIDENCE`. The scoped repair did not clear them, so the answer fell back and nothing was shown | P1 | **fixed offline** in PR `#21` (below), **Live unverified**. The frozen run's outcome for W19 stays failed |
| I-7 | **An explanation kept open that the answer's own timing rules out** | W18 (Live, 2026-09-30): the opening says timing rules the Hazelwood bus-tie outage out. The notice gives 1100 hrs 20/08, after every high-price interval. A hedged hypothesis resting on that notice [c1] still offers it as a possible influence | P2 | **fixed offline** in PR `#22` (below), **Live unverified** |
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

**I-3 and I-4 (P2).**
- **I-3, clear presentation:** F01's "150" without "MW", F03's "1630 hrs" without its zone, and vague headlines.
- **I-4, internal details in user-facing text:** tool names, controller notes and evidence IDs.

**Fixed offline, Live unverified:** I-7 (W18's kept-open explanation, P2) in PR `#22`, and I-6 (W19's fallback, P1) in
PR `#21`. Both were found in the development-only Live check of 2026-09-30
(`artifacts/live/live-check-p1-dev/REVIEW.md`).
- **In that check,** I-1a, I-2a and I-2b held on their development cases, and I-1b failed on W19.
- **This is development evidence,** not generalisation.
- **A fresh, independent check** of the P1 fixes needs about USD 0.85–1.00. USD 0.41 is left under the USD 5.00 task
  cap, so it is not funded.

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
| I-1a: a causal question about a notice-reported incident gets the answer its timing supports | #16 | offline; Live, development cases only: held on F04 and W18 |
| I-1b: a cited notice's cancellation is stated, and a cancelled forecast is never relied on as active | #17 | offline; Live, development case: **failed** on W19 (fired, then fell back; I-6) |
| I-2a: an event question about other regions gets their prices at the price extreme, traced to source rows | #18 | offline; Live, development cases only: held on F04 and W18 |
| I-2b: a question asking by how much a demand measure changed gets the change, computed by code and traced to both source rows | #19 | offline; departs from checks 4 and 5 as written; Live, development case: held on W04 |
| Live check of the P1 fixes, development cases only (F04, W19, W04, W18), recorded | #20 | Live, USD 0.192 |
| I-6: an exact title of a cited market notice is title text, not numbers, in the numeric check | #21 | offline; **Live unverified** |
| I-7: a hypothesis may not rest on a cited notice whose stated time is after every interval of the event | #22 | offline; **Live unverified** |
