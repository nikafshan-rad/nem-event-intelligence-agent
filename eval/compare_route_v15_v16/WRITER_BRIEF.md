# Writer's brief: 46 held-out questions with their gold (H01–H40, C01–C06)

You are writing 46 analyst questions for a one-off comparison of how an assistant for the Australian National
Electricity Market (NEM) reads questions. The comparison looks only at how each question is understood and routed.
Nothing is answered, so the data does not need to hold an answer. For each question you also write its gold: your own
careful reading of what it means and what the assistant should do with it.

**Work only inside this kit.**
- Do not open, list or search anything outside it, and do not use the web.
- You have no access to the assistant's code, prompts, tests or earlier questions, and you do not need them.
- When you finish, report every file you read and every command you ran (see "Report").

## What is in the kit
- **`CAPABILITIES.md`:** what the assistant supports and how a question should be handled. Read it first.
- **`GOLD_FORMAT.md`:** the record you write for each question.
- **`data/events.json`:** the eight price events the data was selected for, with each event's region, kind, peak
  five-minute interval and window. **`data/coverage.md`:** the period the data covers.
- **Python** with the standard library and `zoneinfo` (`python`); write your scripts in `work/`.
- **`overlap/check_overlap.py`:** checks your questions against hashed 6-word sequences of earlier questions and of
  the assistant's instructions. No earlier text is in the kit.
- **`out/`:** for your output.

## The 46 questions
| IDs | Family | What each question must do | Answerable |
| --- | --- | --- | --- |
| H01–H04 | Plain | H01, H02: a **demand maximum within a market event review**: when, or how high, a named demand measure peaked around one of the events in `data/events.json` (H01 operational demand, H02 dispatch total demand), over the event's window or that event's local day. H03: a **single-interval comparison** of AEMO's operational demand forecast with actual demand for one half-hour, under one named run (issued at a stated time, or the last issued before the half-hour). H04: a **window comparison** over a stated period of at most 24 hours. | all 4 |
| H05–H08 | Ambiguity | Ask about a forecast whose kind the question **does not show**, so that demand, price or weather forecasts are all plausible readings to a careful analyst. Vary the wording and settings. | none |
| H09–H12 | Incidental demand | Each mentions demand **incidentally** (as context, not as what is forecast or measured). H09, H10: then ask about a forecast whose kind is not shown. H11, H12: then ask a supported request whose own words name it (an operational demand forecast request, or a named measure's maximum). | H11, H12 |
| H13–H16 | Negation | Each **declines** something explicitly and asks one supported request. At least one asks a demand maximum within a market event review; at least one declines AEMO's operational demand forecast while asking for something else supported. | all 4 |
| H17–H20 | Background | Each reports someone else's statement about a forecast or demand as **background**, then asks one supported request. H17, H18: the statement in quotation marks. H19, H20: without quotation marks. | all 4 |
| H21–H24 | Mixed operations | H21: an operational demand forecast comparison **and** a demand maximum. H22: two measures' maxima (operational demand and dispatch total demand). H23: two distinct demand forecast requests (for example two different half-hours, or a forecast value and a comparison over a period). H24: the exception in `CAPABILITIES.md`: a forecast's POE values and the actual value of the **same half-hour** under the **same named run**. | H24 |
| H25–H28 | Mixed kinds | Ask an operational demand forecast request (or a demand maximum) **and** a forecast of another kind (weather, temperature, price or other); the demand request's own words pin it down. | all 4 |
| H29–H32 | Shared scope | One half-hour or period, stated **once**, serves the asked request and another mention (a declined mention, or another kind of forecast asked for). In at least two, the half-hour or period is stated before the words of the asked request. | all 4 |
| H33–H36 | Time roles | H33: a run named by its exact issue time, a target half-hour, and an exact as-of cutoff, three different instants. H34: a half-hour given by clock times only, in a question naming no date, dated by an exact as-of cutoff given as a UTC timestamp (`CAPABILITIES.md`, "Dates"). H35: a target time restated in brackets in another time zone. H36: the newest run public by an exact as-of cutoff, for one half-hour. | all 4 |
| H37–H40 | Request overrides | Use request fields. H37: `as_of_utc`, with the question's own cutoff words naming a time that cannot be pinned down (for example "by lunchtime"). H38: `window_start_utc` and `window_end_utc` for a demand maximum whose question also names a day. H39: `as_of_utc` with a question naming no cutoff. H40: `window_start_utc` and `window_end_utc` for a window comparison. | all 4 |
| C01–C06 | Known-unsupported controls | Each pins down everything except one time the assistant cannot pin down (`CAPABILITIES.md`): C01 "noon", C02 "midday", C03 a part of the day, C04 a forecast period over 24 hours, C05 a half-hour whose start or end is not stated, C06 a clock time with no time zone. Outcome `clarify`; set `unsupported_time`. | none |

**Every question:**
- **The setting:** it reads as a real analyst's question, in scope: a NEM region, the data period (`coverage.md`), no
  trading, bidding or advice. Forecast questions name dates between 28 July 2026 and 20 August 2026.
- **One date:** it names one calendar date at most. Other instants (an issue time, a cutoff on another day) are given
  as exact UTC timestamps such as `2026-07-30T18:56:59Z`.
- **Answerable questions** pin down every detail of their request: the region; what is asked; the half-hour or period,
  with its date and, for clock times, its time zone; and, when asked, the run and the cutoff, exactly.
- **No answer:** it contains no answer, and no number that the answer would give.
- **Request fields:** only H37–H40 use them; every other `request` is `{}`.
- **Variety:** vary the regions, dates, measures and wording across the questions.
- **No reuse:** write your own words. The overlap checker must print `cases with overlap: none`.

## Your output
- Write `out/heldout.json`, in the form `{"cases": [ ... ]}`, one record per question as `GOLD_FORMAT.md` describes,
  with `"config"` set to its ID and an extra field `"family"` (`plain`, `ambiguity`, `incidental`, `negation`,
  `background`, `mixed_operations`, `mixed_kinds`, `shared_scope`, `time_roles`, `overrides`, `control`).
- Compute every UTC bound and every local-time equivalent with code in `work/`.
- Run `python overlap/check_overlap.py`. It must print `cases with overlap: none`. If not, reword the flagged
  questions in your own words and run it again.

## Report
Give, in your final reply:
1. every file you opened;
2. every command you ran;
3. a confirmation that you opened, listed, searched and ran nothing outside the kit, and did not use the web;
4. the overlap checker's final output;
5. your judgement calls: anything a careful analyst might read differently, and why you chose your reading.
