# Comparative routing-only evaluation: route contract v15 (default) and v16 (request plan, V1)

**Pre-registered before any held-out question is written. Not run.** The owner approved this offline preparation
(2026-10-05); it is not approval for paid execution. A paid run needs a separate approval that names the accounting
path (below), the approved spend and this protocol's freeze commit.

## What this is
- **Two arms, identical except for the routing contract:**
  - **A (baseline):** the default Live path, route contract v15 with prompts v16;
  - **B (candidate):** the opt-in path (`NEM_AGENT_ROUTE_PLAN=1`), route contract v16 with prompts v17, stated-basis
    policy **V1** (`NEM_AGENT_PLAN_POLICY=V1`).
- **The same for both:**
  - one frozen code commit, whose `src/` tree is `main` `76c4341`'s;
  - the model alias `gpt-5-mini`, with the snapshot the API reports recorded;
  - the provider's default reasoning effort (none sent);
  - the routing output cap **unchanged at 2,000 tokens**;
  - identical questions and request fields;
  - one frozen order of all slots, shuffled once and interleaving the arms;
  - no retries;
  - one session.
- **Routing only.** A slot is one routing call (`LiveController.route`) and code's request resolution
  (`service.resolve_routed`), with the tools Live would offer. No dispatcher is created, no tool runs, nothing is
  computed or written as an answer.
- **V0** is not a paid arm. After a run, B's recorded plans are recompiled offline under V0 and reported as
  descriptive only. No policy is selected from this evaluation, and none from held-out results.
- **No application code, prompt or default changes.** Everything here lives in `eval/compare_route_v15_v16/` and
  its tests.

**Passing supports an end-to-end held-out check only. It does not authorize default enablement.**

## The sample: 69 configurations, 322 slots
| Set | Configurations | Repeats per arm | Slots |
| --- | --- | --- | --- |
| Held-out, independently written | 40 | 3 | 240 |
| Known-unsupported controls (held-out, labelled) | 6 | 3 | 36 |
| Development | 23 | 1 | 46 |
| **Total** | **69** | | **322 (161 per arm)** |

- **Development (23):** the 17 v15 diagnostic configurations (`eval/livecheck_route_v15/cases.json`) and the 6
  saved end-to-end records of `artifacts/live/LC-e2e-v13-run` that are not duplicates: E2E-D01, E2E-D02, F02, F06,
  F07N and F08. R02 duplicates v15 D02, and F07 duplicates v15 D10 (same question and request fields). F07N is kept:
  it is F07's question without the request cutoff. Development results are reported separately and never enter an
  adoption criterion, except the B-wide critical and omission gates.
- **Held-out families (4 questions each, 40):**

  | Family | Questions | Answerable |
  | --- | --- | --- |
  | 1. Plain supported requests (2 demand maxima in event reviews; 2 demand forecasts) | 4 | 4 |
  | 2. Ambiguity: a forecast whose kind is not shown | 4 | 0 |
  | 3. Incidental demand mentions (2 with an unnamed forecast; 2 with a named supported request) | 4 | 2 |
  | 4. Negation: a declined mention and an asked supported request (at least 1 maximum in an event review) | 4 | 4 |
  | 5. Background: 2 in quotation marks, 2 without, each with an asked supported request | 4 | 4 |
  | 6. Mixed operations: 3 with two distinct supported asked requests (including one with a maximum); 1 with a value and a comparison of the same half-hour under the same named run | 4 | 1 |
  | 7. Mixed kinds: an asked demand request and an asked forecast of another kind | 4 | 4 |
  | 8. Shared scope: one half-hour or period serving the asked request and another mention | 4 | 4 |
  | 9. Time roles: target, issue time and cutoff each distinct; a clock-only half-hour dated by its cutoff; a bracket restating a time | 4 | 4 |
  | 10. Request overrides: request fields (`as_of_utc`, `window_start_utc`/`window_end_utc`), including a question cutoff code cannot read under an authoritative request cutoff | 4 | 4 |
  | **Total** | **40** | **31** |

- **Known-unsupported controls (6):** "noon", "midday", a part of the day, a forecast period over 24 hours, a
  half-hour whose start or end is not stated, and a clock time with no time zone. Each must be sent back safely.
  They are labelled, kept out of the availability denominator, and gated for B only.
- **Answerable** means a correct system resolves exactly one supported request, fully pinned down. The writer must
  meet the family quotas above; the frozen gold fixes each question's membership. **The availability denominator is
  frozen with the gold: 31 answerable held-out questions (93 slots per arm)**, or the number the frozen gold records
  if a replacement round (below) changes it, which `freeze.py` writes and the scorer reads.

## The gold (`GOLD.json`): written, reviewed, frozen before any call
1. **This protocol, `CAPABILITIES.md`, `GOLD_FORMAT.md` and the briefs** are committed before any held-out question
   is written.
2. **The writer:** a fresh agent working only in a kit outside the repository (`build_kit.py writer`), with the
   capability description, the gold format, the data facts, Python with `zoneinfo`, and an overlap checker holding
   hashes of every 6-word sequence of earlier questions, the prompts and the D31 tests (no earlier text). It writes the
   46 held-out configurations, each with its gold record, and must reach `cases with overlap: none`.
3. **The development gold** is derived by `gold.py` from the frozen, verified gold of the v15 check and the saved
   end-to-end records (read only; nothing there changes), into the same format.
4. **The reviewer:** a second fresh agent, in its own kit (`build_kit.py reviewer`), sees all 69 questions with their
   request fields only (no gold, no family, no set) and writes its own reading of each, blind.
5. **Comparison:** `gold.py --compare` checks every gated item (below). For a held-out disagreement:
   - the writer sees only the reviewer's reading of that question and may revise its record, or defend it;
   - the reviewer then sees only the writer's final record of that question and accepts or rejects it;
   - still in disagreement: the writer replaces the question with a new one in the same family, which the reviewer
     reads blind; one replacement round only;
   - still in disagreement: the question is dropped, and the shortfall is recorded. The denominators follow the
     frozen gold.

   Development disagreements are reported; the development gold, taken from verified sources, is not changed by this
   evaluation.
6. **The developer writes no held-out question and no held-out gold item,** and settles no disagreement.
7. `PROVENANCE.md` records the order, the hashes, the agents' reports and every disagreement.

**Gated gold items:** acceptable outcomes; answerable; region; intents; each mention's stance (by anchor overlap);
the primary request's kind and subject; the resolution's operation, scope kinds and bounds, run rule, target end and
issue time, cutoff, maximum (measure, window kind, bounds) and not-answered kinds; tool eligibility; the
known-unsupported label.

## Scoring (`score.py`, offline; never calls a model)
Three layers are kept apart, and attribution crosses the first two.

### Layer 1: the model's extraction, independent of the resolver
- **Common items, scored for both arms,** only where both contracts can represent the information:
  - intent (in the gold's intents), region, event date (in the gold's local dates);
  - the primary asked request's subject (a forecast's domain, or a maximum's measure) and operation class;
  - its scope: the kind is one the gold accepts, and the model's words contain every scope key word;
  - its run rule, with words containing the run key words;
  - its cutoff: words containing the cutoff key words, or none where the gold has none;
  - another kind of forecast asked alongside, named on its anchor;
  - declined or background mentions not read as the request (no request words overlap their anchors);
  - for a question with no supported request: what is forecast, as the model reads it (an unclear kind, or another
    kind).
- **Judged by the words, never by conversion:** a reading whose words hold every key word is correct even when code
  cannot convert them (for example "noon"). That is a resolver limitation, attributed in layer 2.
- **v15 is never marked wrong** for lacking a stance field, references, or a second request. For a question with two
  asked supported requests, the common items are intent, region, date, and whether the request the model read is one
  of the gold's asked requests.
- **Plan-only items (B, reported separately):** each mention's stance; the primary operation's scope, run and cutoff
  references (present when the gold has them, absent otherwise, and pointing to entities whose words hold the key
  words); the plan-level cutoff; located entity words.

### Layer 2: resolution and tool eligibility, against the same gold for both arms
Each slot's resolution is classified by one arm-neutral definition:
- **Outcome:** `resolved` (it proceeds with a bound supported request), `clarify` (sent back; nothing bound),
  `refusal`, or `event_review_without_demand_forecast` (an event review proceeds, the demand-forecast tools are not
  offered, and the forecast is named as not answered or as unclear).
- **Exact resolution:** outcome `resolved`, the gold's region, an intent in the gold's intents, every bound field
  equal to the gold's resolution, the not-answered kinds exactly the gold's, tool eligibility as the gold says, and no
  critical violation.
- **Critical violations** (any arm, any set):
  - **C1** a demand-forecast tool offered where the gold says demand tools are not used;
  - **C2** a resolution that proceeds with a cutoff other than the gold's (dropped, added or different);
  - **C3** a resolution that proceeds with a bound region, operation, half-hour, period, run, issue time, measure or
    window other than the gold's, or with a bound request where the gold resolves none;
  - **C4** declined or background words read as a bound request (its evidence words overlap their anchors);
  - **C5** a known-unsupported control that proceeds;
  - **C6** any tool executed, or any case-note write.
- **Silent omission:** a gold-asked supported request (a demand forecast or a demand maximum) that, in a resolution
  that proceeds, is neither bound nor named as not answered. A question with two distinct supported asked requests
  that proceeds with one bound and the other named (by any not-answered or unclear-forecast note) is **partial**:
  reported for both arms, never an acceptable outcome, and not a silent omission. A maximum is named by no existing
  note, so an unbound asked maximum in a proceeding resolution is always a silent omission.
- **No reading:** a rejected response (incomplete, invalid), an API error or an interrupted slot.

### Attribution
Layer 1 × layer 2, per slot: correct end to end; correct reading rejected by code; correct reading mis-resolved by
code; incorrect reading caught by code; incorrect reading accepted by code; no reading.

## Acceptance criteria (B; A's failures are baseline findings)
**Definitions frozen before any call:**
- **Availability:** exact resolutions over all held-out answerable slots of an arm (31 questions × 3 repeats = 93),
  counting every no-reading slot as not exact.
- **Incomplete rate:** routing responses cut off (`status` incomplete) over all held-out slots of an arm (46 × 3 =
  138).
- **The interval:** a paired bootstrap clustered by question. Each resample draws the answerable held-out questions
  with replacement, keeping each question's repeats in both arms together, and computes B's availability minus A's
  over the drawn slots. 10,000 resamples; seed `20261005`; the 5th and 95th percentiles form the 90% interval.
- **Reported always:** raw counts per call (x of n per arm), and per question (how many questions reach 3, 2, 1 and 0
  exact repeats, per arm), beside every rate and the interval.

**The verdict, in this order:**
1. **B FAILS** if any B slot (any set) shows a critical violation (C1–C6) or a silent omission. Zero observed is
   required; it does not establish a zero failure rate. Infrastructure problems never erase an observed violation or
   omission.
2. **INCOMPLETE** if any frozen slot has no terminal record (below).
3. **INCONCLUSIVE** if API errors and interrupted slots together exceed 5% of either arm's 161 slots (more than 8).
4. **MET** only if all hold, else **NOT MET** with each unmet criterion named:
   1. B's availability is at least **15 percentage points** above A's, and the interval's lower bound is above 0;
   2. B's availability is at least **80%**;
   3. B's incomplete rate is at most **5 percentage points** above A's;
   4. all **18 of 18** B control slots are sent back safely (no binding, no demand-forecast tool offered);
   5. B's median settled cost per routing call is at most **1.5 times** A's.

**The thresholds** (15 points, 80%, 5 points, 1.5 times) are the owner's practical thresholds for a migration
decision, not statistical standards: 15 points is the smallest gain judged worth the migration, given v15's measured
supply of 3 of 20 diagnostic calls; 5 points bounds the added truncation risk of the larger plan output, which
availability already counts.

**Limits of the interval:** the questions are deliberately selected by family, not sampled from real traffic; repeats
of one question are correlated and are kept together; the interval describes the stability of the difference over
these questions under these settings, not a population rate, and supports no generalisation.

## What routing-only evidence cannot establish
- whether answers are correct, or whether results are available in the data held;
- how validators, repairs and fallbacks behave, or how often fallbacks happen;
- the quality of the model's interpretation, and truncation during synthesis;
- whether the echo and the clarification texts work for a real reader;
- tool-call behaviour, and the cost and latency of a full investigation;
- generalisation beyond the questions written.

## Caps and accounting
- **Reservations:** each configuration's worst-case reservation for each arm is measured by `freeze.py` on the
  actual runner code path (`run_route.route_call` with a stub transport; `budget.reserve` captured, nothing written),
  and frozen per slot.
- **The run cap** is the exact sum of the 322 frozen slot reservations. **The maximum approved budget prepared
  against is USD 2.00**; `freeze.py` refuses to freeze a run cap above it. Neither is an authorization to spend.
- **Two independent enforcements:**
  - **the ledger** (`nem_agent.budget`): each slot runs with `NEM_AGENT_TOTAL_BUDGET_USD` set to the ledger total
    before the slot plus that slot's frozen reservation, so no call can reserve more;
  - **the runner's conservative account:** a slot starts only if the conservative spend so far plus its frozen
    reservation is within the run cap.
- **Accounting kept apart, per slot and in total:**
  - **reserved:** the frozen worst-case reservation;
  - **settled:** the ledger's change during the slot (the application settles a completed call at its usage-priced
    cost, an HTTP 4xx at zero, and other errors at the worst case);
  - **observed usage:** the tokens and usage-priced cost of a response the slot actually received, or none;
  - **unresolved:** a slot with no observed usage (an API error of any kind, including HTTP 4xx, or an
    interruption), whose cost is not known;
  - **conservative:** observed usage cost where observed, otherwise the full reservation. The run cap is enforced on
    this, never on the ledger's settled amount.
- **Billed usage** is not observed by the API. If the owner reads the provider's usage page for the run window, it is
  recorded separately (`BILLED.md`) and never written into a ledger.

### Accounting paths (the paid approval names one)
- **historical:** the run appends to the historical ledger, which must first be found and match, read-only, its
  recorded state: USD 9.336937, 3,226 lines, SHA-256 prefix `f303c2bc70aadd8f`. It was not found on the preparing
  machine (the Windows profile and the WSL filesystem hold no `ledger.jsonl`; Codespaces could not be listed without a
  token scope the owner has not granted).
- **evaluation:** a separate ledger, `artifacts/live_budget/CMP-route-v15-v16.ledger.jsonl` (git-ignored), which must
  be absent or empty at the first start. The task-wide total is then reported as "USD 9.336937 as previously recorded,
  not verified locally, plus this evaluation's settled and conservative amounts". The historical ledger is never
  reconstructed, back-filled or replaced.

## Slots, stops and completeness
- **A slot is attempted** once its process starts. It is never retried or repeated because of its result.
- **Terminal records:**
  - **saved:** the routing response was received and resolved (complete, incomplete or invalid);
  - **api_error:** the call raised (any HTTP status, timeout or connection error); recorded with its status code and
    ledger change, counted as no reading and as unresolved;
  - **interrupted:** the process ended without a record; found at the next start, counted as no reading, unresolved
    and at its full reservation, and not started again.
- **Stops (the rest are not run; the evaluation is INCOMPLETE):** the conservative start guard or a ledger budget
  refusal; a change to frozen files or `src/`; a safety failure (C6).
- **Complete:** every frozen slot has exactly one terminal record, and the slot accounting reconciles with the ledger
  (settled change per slot, and the total).
- **Refusals:** the lock is held; frozen files or `src/` differ; the plan does not match the configurations; the record
  directory holds records the log does not account for; a ledger, cap, price, model or route-plan override is set by
  the caller; the accounting path is not named, or its ledger is not in the required starting state; no API key is set
  (never read or printed); the approved spend is below the run cap; the evaluation has ended.

## Records
- Per slot: the decision (v15 or v16 plan), the contract, the prompts read, the full resolution and its plan record,
  the tools Live would offer, the routing call's status, usage and duration, the reported model, and the slot's
  accounting.
- The run log (`run_log.jsonl`), the scored report (`SCORE.json`) and a written report.

## Known before the run (offline, scripted plans)
The merged compiler's recorded limitations apply to B and are measured, not assumed: trusted stances, undetected
omissions (notably an omitted maximum in an event review), provenance that is not meaning, and the known-unsupported
time expressions. A, under its existing resolver, is expected to lose some correct readings to clause containment.
