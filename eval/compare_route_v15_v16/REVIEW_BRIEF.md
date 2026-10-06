# Reviewer's brief: an independent reading of 69 questions

You are checking the gold of a one-off comparison of how an assistant for the Australian National Electricity Market
(NEM) reads analysts' questions. The comparison looks only at how each question is understood and routed. Nothing is
answered.

You see the questions only. You do not see the gold you are checking, any intended reading, or why a question was
written. Give your own careful reading of each question.

**Work only inside this kit.**
- Do not open, list or search anything outside it, and do not use the web.
- You have no access to the assistant's code, prompts, tests or gold, and you do not need them.
- When you finish, report every file you read and every command you ran (see "Report").

## What is in the kit
- **`CAPABILITIES.md`:** what the assistant supports and how a question should be handled. Read it first.
- **`GOLD_FORMAT.md`:** the record you write for each question.
- **`questions.json`:** the 69 questions, with their IDs and request fields. A request field is authoritative.
- **`data/events.json`**, **`data/coverage.md`:** the eight price events and the period the data covers.
- **Python** with the standard library and `zoneinfo` (`python`); write your scripts in `work/`.
- **`out/`:** for your output.

## What to do
- **For each question,** decide what it means and what the assistant should do with it under `CAPABILITIES.md`, and
  write one record as `GOLD_FORMAT.md` describes. The `family` field is not needed.
- **For a question you judge could reasonably be read in two ways,** give the outcome you think the assistant should
  choose, list every outcome you would accept in `acceptable_outcomes`, and describe each reading in `notes`. When
  `resolved` is acceptable, fill in that reading's `resolution`.
- **Compute every UTC bound,** and every local-time equivalent, with your own code in `work/`. Do not copy a bound from
  anywhere.
- **Write** `out/review.json` in the form `{"cases": [ ... ]}`.

## Report
Give, in your final reply:
1. every file you opened;
2. every command you ran;
3. a confirmation that you opened, listed, searched and ran nothing outside the kit, and did not use the web;
4. your judgement calls: each question where a careful analyst might read differently, and why.
