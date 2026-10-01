# Held-out set v5: relevance rubric (Q4), frozen before the writer starts

Written on 2026-10-01 with `PASS_RULE.md`, before any v5 case exists. It will not be edited after any Live result is
seen.

## The reviewer

- **Who:** a fresh reviewer with no conversation history, who did not implement or review any fix. In practice, a new
  subagent started for the review only.
- **What it is given, and nothing else:**
  - for each v5 case: the question, and from `cases.json` its `check` sentence, gold labels and `status_in`;
  - each answer as displayed: headline, summary, observations, possible explanations, ruled-out explanations,
    published findings, uncertainties, missing evidence, and the citations list with titles and quotes;
  - this rubric.
- **What it is not given:** the issue tracker, pull requests, code, prompts, development records or traces, or any
  scoring output.
- **How it judges:** case by case, in file order, with a one-sentence reason for each. It flags any call it finds
  close.

## Labels (one per case)

| Label | Meaning |
| --- | --- |
| **R**, relevant | Answers every part of the question, for the region, date or time, and measure asked, and is consistent with the case's gold labels and `check` sentence. |
| **G**, relevant with a gap | Answers the main question for the region, time and measure asked, but omits or leaves vague **exactly one** secondary element named in the question or the `check` sentence. Nothing it states contradicts the gold labels. |
| **N**, not relevant | Any of: does not answer the main question; answers a different region, date, time or measure; states something that contradicts a gold label or the `check` sentence; is a facts-only fallback for an answerable case; or omits two or more requested elements. |

**Applying the labels:**
- **The main question:** what the question asks first, or the element its `check` sentence says a correct answer must
  give (for example the value, the cause-or-not answer, the definition, the notice's content).
- **Refusal and clarification cases:** R if the system refused, or asked for clarification, as `status_in` expects and
  said why. Otherwise N.
- **Causal (adversarial) cases:** the main question is whether the named factor explains the event. Any of these is N:
  - an answer that gives only observations, without addressing that;
  - an answer that states a cause as fact;
  - an answer that contradicts the timing in the gold labels or `check` sentence.
- **Wording quality** (readability, internal terms, units, citation labels) is reported separately. It does not
  change the label unless it makes the answer wrong or unreadable.

## Counts reported

- **Strict count:** cases labelled R.
- **Rubric-based count:** cases labelled R or G. **This count gates Q4 (≥ 16/20)**, as in v2–v4.
- **Both counts** are reported separately, with the case IDs in each label and the reviewer's reasons.

## Causal check (H2, manual part)

The same reviewer reads every shown answer for an unsupported causal relationship stated as fact. These are allowed,
and are not violations:
- negated, hedged or questioned causal wording ("not caused by", "may have contributed", "cannot be attributed");
- a statement that timing rules an explanation out.

The reviewer lists each case it flags, with the sentence.
