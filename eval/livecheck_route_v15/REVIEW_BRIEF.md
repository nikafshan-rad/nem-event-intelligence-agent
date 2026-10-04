# Reviewer's brief: an independent reading of seventeen questions

You are checking the gold of a one-off check of how an assistant for the Australian National Electricity Market
(NEM) reads analysts' questions about forecasts. The check looks only at how each question is understood and routed.
Nothing is answered.

You see the questions only. You do not see the gold you are checking, or any intended reading. Give your own careful
reading of each question.

**Work only inside this kit.**
- Do not open, list or search anything outside it, and do not use the web.
- You have no access to the assistant's code, prompts, tests or gold, and you do not need them.
- When you finish, report every file you read and every command you ran (see "Report").

## What is in the kit
- **`CAPABILITIES.md`:** what the assistant supports and how a question should be handled. Read it first.
- **`GOLD_FORMAT.md`:** the record you write for each question.
- **`questions.json`:** the 17 questions, with their configuration IDs and request fields. A request field is
  authoritative.
- **`data/events.json`:** the eight price events the data was selected for, with each event's region, kind, peak
  five-minute interval and window.
- **`data/coverage.md`:** the period the data covers.
- **`venv/`:** Python with only the standard library (`venv/bin/python`); `zoneinfo` works for time zones.
- **`work/`:** for your scripts.
- **`out/`:** for your output.

## What to do
- **For each question,** decide what it means and what the assistant should do with it under `CAPABILITIES.md`. Then
  write one record as `GOLD_FORMAT.md` describes:
  - the outcome, and every outcome you would accept;
  - the region, domain, operation and scope;
  - the run selection and cutoff;
  - any maximum;
  - the request anchors and excluded anchors;
  - any unsupported parts;
  - tool eligibility.
- **For a question you judge could reasonably be read in two ways,** give the outcome you think the assistant should
  choose, and list every outcome you would accept in `acceptable_outcomes`.
  - **When `resolved` is among them:** fill in that resolved reading's fields in the record, even if your `outcome`
    is a clarification. That means the operation, scope and bounds, run selection, cutoff, anchors and tool
    eligibility of that reading.
  - **In `notes`:** describe each reading.
- **Compute every UTC bound,** and every local-time equivalent, with your own code in `work/`. Do not copy a bound
  from anywhere.
- **Write** `out/review.json` in the form `{"cases": [ ... ]}`.

## Report
Write `out/REPORT.md` with:
1. every file you opened;
2. every command you ran;
3. a confirmation that you opened, listed, searched and ran nothing outside the kit, and did not use the web;
4. your judgement calls: each question where a careful analyst might read differently, and why.
