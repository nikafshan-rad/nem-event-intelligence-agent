# Writer's brief: seven questions about forecasts (N01–N07)

You are writing seven analyst questions, N01–N07, for a one-off check of how an assistant for the Australian
National Electricity Market (NEM) reads questions about forecasts. The check looks only at how each question is
understood and routed. Nothing is answered, so the data does not need to hold an answer.

**Work only inside this kit.**
- Do not open, list or search anything outside it, and do not use the web.
- You have no access to the assistant's code, prompts, tests or earlier questions, and you do not need them.
- When you finish, report every file you read and every command you ran (see "Report").

## What is in the kit
- **`CAPABILITIES.md`:** what the assistant supports and how a question should be handled. Read it first.
- **`GOLD_FORMAT.md`:** the record you write for each question: your reading of it, which is the check's gold.
- **`data/events.json`:** the eight price events the data was selected for, with each event's region, kind, peak
  five-minute interval and window.
- **`data/coverage.md`:** the period the data covers.
- **`venv/`:** Python with only the standard library (`venv/bin/python`); `zoneinfo` works for time zones.
- **`overlap/check_overlap.py`:** checks your questions against hashed 6-word sequences of earlier questions and of
  the assistant's instructions. No earlier text is in the kit.
- **`work/`:** for your scripts.
- **`out/`:** for your output.

## The seven questions

| ID | What the question must do | Expected handling |
| --- | --- | --- |
| N01 | Ask only for a **temperature** forecast, asking for its highest or maximum value (for a city, on a date) | not answered with demand forecasts |
| N02 | Ask only for **AEMO's price forecasts** (for example predispatch prices) for a region on a past date in the data period | not answered with demand forecasts |
| N03 | Ask about **"the forecasts"** for a region and date in a way that does **not** show what was forecast, so that demand, price or weather forecasts are all plausible readings. It must be genuinely ambiguous to a careful analyst, not a demand question in disguise | which forecast is meant must be asked |
| N04 | **Decline** a weather or temperature forecast explicitly, and ask for **AEMO's operational demand forecast** for a region: a forecast value or a comparison with actual demand, for one half-hour, a whole local day, or a stated period of at most 24 hours | the demand request resolved |
| N05 | **Decline** AEMO's operational demand forecast explicitly, and ask for a **weather or temperature** forecast | not answered with demand forecasts |
| N06 | Quote, in quotation marks, **someone else's statement about a demand forecast** as background, then ask for a **temperature or weather** forecast | not answered with demand forecasts |
| N07 | Quote, in quotation marks, **someone else's statement about a weather forecast** as background, then ask how **AEMO's operational demand forecast compared with actual operational demand** for a region, over one half-hour or a whole local day or a stated period of at most 24 hours | the demand request resolved |

**Every question:**
- **The setting:** it reads as a real analyst's question. It is in scope: a NEM region, a date in the data period
  (`data/coverage.md`), and no trading, bidding or advice.
- **The date:** it names exactly one date. Do not use a second date anywhere in the question, even in the quoted
  background.
- **No answer:** it contains no answer, and no number that the answer would give.
- **Request fields:** none. The `request` is `{}`.
- **Variety:** vary the regions, dates and wording across the seven questions.
- **No reuse:** write your own words. The overlap checker must print `cases with overlap: none`.

**N04 and N07,** which are to be resolved, must pin down every detail of the demand request:
- the region;
- what is asked (the operation);
- the half-hour or period, with its date and, for clock times, its time zone.

If they name a cutoff, it must be exact, with its date, time and time zone. If they ask for one specific forecast run,
the run must be pinned down too.

**N01, N02, N05 and N06** ask for nothing the assistant provides, apart from the declined or quoted parts.

## Your output
- Write `out/fresh.json`, in the form `{"cases": [ ... ]}`, with one record per question as `GOLD_FORMAT.md`
  describes.
- **Your record is the gold for that question:** your own careful reading of what it means, and what the assistant
  should do with it under `CAPABILITIES.md`.
- Compute every UTC bound, and every local-time equivalent, with code in `work/`.
- Then run `venv/bin/python overlap/check_overlap.py`. It must print `cases with overlap: none`. If it does not,
  reword the flagged question in your own words and run it again.

## Report
Write `out/REPORT.md` with:
1. every file you opened;
2. every command you ran;
3. a confirmation that you opened, listed, searched and ran nothing outside the kit, and did not use the web;
4. the overlap checker's final output;
5. your judgement calls: anything a careful analyst might read differently, and why you chose your reading.
