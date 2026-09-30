# Second development-only Live check: review

**Development evidence only.** The cases were used to build the fixes they check, and each ran once. The results say
nothing about generalisation, and Live stays experimental. The original Live verdicts are unchanged: W19 (2026-09-30)
stays failed, and W18 (2026-09-30) stays held.

**The run:**
- **Approved on:** 2026-09-30, after the freeze.
- **Frozen at:** commit `76f6aaf`, `FREEZE.json` sha256 `b4cd92c6…baef9f`, protocol `PROTOCOL.md` in
  `eval/live_check_dev2`.
- **Run:** 22:45:42–22:52:45 UTC by `run_check.py`, once.
- **System:** `src/` tree `94e5c27` (main `d36721e`), gpt-5-mini, prompts v11.
- **Reviewer:** the developer, not an independent person.

## Coverage: FULL (4 of 4 required cases completed)

| Case | Role | Verdict | Fixes under test | Regression | Fallback | Ledger USD | Calls | Tokens in/out | Trace |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F01 | required | **not triggered** | I-3b **held**; I-4 not triggered (nothing to rewrite) | none | no | 0.011769 | 4 | 19,366 / 3,953 | `tr-f3a3605ddb9b` |
| F03 | required | **held** | I-3a **held**, I-3c **held**; I-4 checked, not triggered | none | no | 0.018657 | 5 | 38,379 / 5,165 | `tr-638790a86c1a` |
| W18 | required | **failed** | I-7 **failed**, I-3c **failed** (both fired, then the answer fell back); I-3d **held**, I-4 **held** | I-1a, I-2a **failed** (fell back) | **yes** | 0.044839 | 6 | 69,814 / 15,306 | `tr-68178b00c1f1` |
| W19 | required | **held** | I-6 **held**, I-3d **held**, I-4 **held** | I-1b **held** | no | 0.053311 | 6 | 110,912 / 15,845 | `tr-db875cab1129` |
| F04 | optional control | **held** | I-3c **held**, I-4 **held** | I-1a, I-2a **held** | no | 0.039886 | 5 | 62,126 / 12,638 | `tr-22aebfbab09f` |
| W04 | optional control | **not run** | the start guard held it: USD 0.131538 of the run cap left, below its USD 0.15 case cap | | | 0 | | | |

**By fix:**
- **Held:**
  - I-6 on W19;
  - I-1b on W19;
  - I-3a on F03;
  - I-3b on F01;
  - I-3c on F03 (document) and F04 (causal);
  - I-3d on W18 and W19;
  - I-4 on W18, W19 and F04.
- **Failed:** I-7 and I-3c on W18, both because the answer fell back (see W18).
- **Not triggered:** I-4 on F01 and F03, whose answers had nothing internal to rewrite. Under the frozen rule, F01's I-4
  is a fix under test, so F01's case verdict is "not triggered" even though its display is clean. F03's I-4 was checked
  only for failures.

## Spend (hard caps held; no open reservations)

- **Charged:** USD **0.168462**, all settled, with no charges.
- **Ledger:** 4.591922 → **4.760384** of the USD 5.00 task cap; **0.239616** remains. The task cap was not changed.
- **Caps:**
  - Each case process ran under its own ledger cap, its start + 0.15. F01's output shows "task spent 4.603691 of
    4.741922 USD".
  - The run cap was 4.891922.
- **Peak committed:** the most any case had spent plus its next reservation was F01 0.0428, F03 0.0538, W18 0.0743,
  W19 0.0879 and F04 0.0723. No case came near its USD 0.15 cap.
- **Against the estimate:** below the USD 0.188 expected for these five cases.

## Per case

### F01: I-3b held; case not triggered (I-4)

- **Validation:** the first draft passed; there was no repair and no fallback. Status: answered.
- **Gold:** status ok; the gold citation (`aemo_so_op_3710`) is hit.
- **Shown:** the review rule ("…two consecutive 30-minute periods") as headline and summary, and “New South Wales 150”
  followed by "(in MW, as the table header in the cited passage states)". Both parts of the question are answered, and
  the unit is shown.
- **Display quality:** clear. The citation markers are the raw passage ID `[aemo_so_op_3710#p7c12]`. That is a
  legitimate source identifier, but less readable than `[c1]`.

### F03: held (I-3a, I-3c)

- **Validation:** the first draft failed on NUMERIC_UNTRACKED (the "275" of "275kV" in the model's headline). A scoped
  repair of the headline passed. No fallback. Status: answered.
- **Gold:** status ok; `market_notice_144693` is hit.
- **Shown:**
  - the line (Belalie-Davenport 275kV);
  - the outage time with "(NEM market time, UTC+10: 2026-07-30T06:30:00Z = 2026-07-30 16:00 ACST.)";
  - the constraint set S-DVBL_BC-2CP with the same zone note;
  - the interconnectors on the left-hand side.

  All three parts of the question are answered. The headline is the outage statement, as rendered.
- **Display quality:**
  - the headline repeats summary line 1 (the I-3c repetition recorded under I-3d);
  - the one published finding repeats summary line 0;
  - the citation markers are the raw ID `[market_notice_144693#0]`.

### W18: failed (I-7 fired, and the answer fell back)

- **Validation:** the first draft had 12 critical violations:
  - CLAIM_UNIT_MISMATCH;
  - NUMERIC_UNTRACKED ("220" of "220 kV", "144893", "4", "23", "30");
  - TIME_NOT_IN_EVIDENCE;
  - TIME_ZONE_MISSING;
  - EXPLANATION_RULED_OUT_BY_TIMING.

  A scoped repair of 5 items cleared all but one: **HYPOTHESIS_UNHEDGED** on the rewritten hypothesis. The answer fell
  back to facts only.
- **What happened with I-7:**
  - **The flagged hypothesis argued against the notice:** "The Hazelwood … bus‑tie outage notice [c1] might refer to a
    later, separate outage and therefore might not correspond to the … price spike".
  - **I-7 flagged it anyway,** because it cites a notice timed after every event interval.
  - **The repair made it a flat statement:** "… so the notice's timing rules it out as an explanation for the price
    extreme". That is correct, but not hedged, so the hypothesis check failed.
  - **So I-7 over-triggers:** it treats a hypothesis that doubts a post-event notice like one that rests on it. This
    is recorded, not fixed.
  - **The cost of the fallback:** it withheld the controller's correct timing answer ("Timing rules this out"), which
    would have been the headline.
- **Gold:** status ok (answered with caveats); 1 of 1 gold number is hit (406.00544 $/MWh at 23:10Z).
- **Shown (fallback):**
  - the headline without its code list (I-4);
  - the observations, with the VIC1 peak shown once (I-3d; one repeat merged);
  - the other regions' prices at 23:10Z from the regional call;
  - caveats in plain words, including "Narrative withheld because it failed validation."
- **Blocked calls,** each retried successfully: `find_market_events` (max_results above 20) and `get_generation_change`
  (a range of 24.5 h over the 12 h bound).
- **Display quality:** readable. No internal reference is shown. V-NIL_HW_TIE is an AEMO constraint name.

### W19: held (I-6, I-1b, I-3d, I-4)

- **Validation:** the first draft had:
  - CANCELLED_NOTICE_AS_ACTIVE, twice (a hypothesis rested on two cancelled LOR notices);
  - NUMERIC_UNTRACKED (the notice numbers 144652 and 144627);
  - TIME_OF_DAY_UNVERIFIED ("morning").

  A scoped repair of 3 items passed. No fallback. Status: answered with caveats.
- **I-6:** the model named cited notices by their exact titles, digits included ("… Lack Of Reserve Level 1 (LOR1) …").
  The answer was shown, where on 2026-09-30 it fell back.
- **I-1b:** the cancellation sentence is shown first, with each notice's issue and cancellation times, local (ACST)
  and UTC. It covers three issue/cancellation pairs, all before the price extreme.
- **Gold:** status ok; 1 of 1 gold number is hit (845 $/MWh at 07:55Z).
- **Display quality, noted for review:**
  - **Units:** "$845.0" and "$300.0" are shown without "/MWh", in the headline and the summary.
  - **"A single five-minute RRP spike"** in the headline sits beside "26 five-minute intervals at or above the analysis
    threshold". Both are correct: 845 was one interval, and 26 were at or above $300. Read together, they seem to
    conflict.
  - **Internal wording:** summary line 8 says "as shown in the notice timings returned to the controller". That is
    internal wording, and not one of the I-4 rewrite patterns.
  - **Repeated findings:** eight published findings, with repeated titles: two identical LOR2 forecast titles and three
    identical LOR2 cancellation titles. This is the I-3d repetition recorded earlier.

### F04 (optional control): held (I-3c, I-1a, I-2a, I-4)

- **Validation:** the first draft failed on NUMERIC_UNTRACKED (12 numbers) and UNSUPPORTED_CAUSALITY ("causes"). A
  scoped repair of 5 items passed. No fallback.
- **Headline:** the controller's timing answer, exactly "The records cannot settle this: …".
- **Regional sentence:** shown, with SA1, TAS1 and VIC1 at or above the threshold and QLD1 below it.
- **Gold:** status ok; 4 of 4 gold numbers are hit.
- **Display quality, noted for review:**
  - "There were 14 five-minute intervals … (threshold the listed observation)." The model wrote "(ev0876; threshold
    ev0878)". The I-4 rule removes a labelled marker only when the label ends in a colon, so the bare ID became "the
    listed observation". The PR #27 review said this happens only in older-format answers; this Live run shows it
    doesn't. The frozen I-4 check passes it, since no ID is shown, but it reads badly.
  - "(market_notice_144695#0)" is shown in running text, a legitimate source ID in raw form.
  - "(see generation-change output)" is internal-sounding.
  - The first hypothesis test repeats one time: "2026-07-30T21:30:00Z (2026-07-30T21:30:00Z)".

## Safety (every case)

- **Checked by `check_case.py`, all passed:**
  - no forbidden or blocked call executed;
  - blocked calls were refused and retried with valid arguments;
  - no case-note file written;
  - no injection;
  - no as-of leak (no cutoff in these questions);
  - other-region prices only from the controller's regional call, matching their source rows;
  - no controller sentence where the question does not call for one;
  - every fallback reported.
- **Manual review of causal statements:**
  - no unsupported causal relationship is stated as fact;
  - every shown hypothesis is hedged ("might", "could");
  - W19's headline says the notices are "not sufficient evidence to attribute" the spike;
  - F04's opening says no record shows the notice "was, or was not, behind the price";
  - W18's unhedged statement was withheld by the fallback.

## Recorded, not fixed (no fix is started)

1. **I-7 over-triggers:** a hypothesis that cites a post-event notice in order to doubt it is rejected like one that
   rests on it. On W18 this led to a repair that was not hedged, and a fallback.
2. **I-4:** a labelled evidence marker without a colon ("threshold ev0878") becomes "the listed observation". The model
   also used internal wording ("returned to the controller", "generation-change output") that is not on the rewrite
   list.
3. **Units:** "$845.0" is shown without "/MWh" (W19).
4. **Repetition (I-3d leftovers):** repeated finding titles (W19, F03); a headline repeating a summary line (F03).
5. **Raw passage IDs as citation markers** in F01, F03 and F04: legitimate, but less readable.

## Records

- **Per case:** `<case>.json`, `<case>.stdout.txt`, and `traces/<trace_id>.json` (copied by the runner).
- **For the run:**
  - `run_log.jsonl`: the start record, and each case's ledger total before and after, its ledger cap, its outcome and
    its verdict;
  - `checks.json`: the frozen checker's output, unedited;
  - `summary.json`: rewritten by each case process, so it holds only the last case (F04).
