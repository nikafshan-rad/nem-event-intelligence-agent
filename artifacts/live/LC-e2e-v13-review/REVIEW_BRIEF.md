# Review brief: the end-to-end Live acceptance check of v13 request resolution

You are reviewing what an assistant showed for each question of a one-off check. It answers analysts' questions about
the Australian National Electricity Market from a pinned copy of public AEMO data.

Your sheet gives, for each answer:
- the question and its request fields;
- what was shown;
- the evidence behind every item shown;
- the gold: the expected answer, computed and checked independently, with its source.

Fill in each answer's `fill` block. Read only your sheet and this brief. Two reviewers read every answer, and the
stricter reading prevails.

## What was shown (`shown`)
- **`computed_answer`:** statements rendered by code from a result that a runtime verifier checked. Each has a
  `status` and a `verification`. `not_verified` means the result was not admitted, and no value of it is given.
- **`summary`, explanations, findings, uncertainties, missing evidence:** the interpretation, written by the model and
  checked by a validator.
- **`label`, `interpretation` and `validation`:** whether the interpretation was validated, withheld because it failed
  validation (a facts-only fallback), or absent.

Read everything shown, the computed answer and the interpretation alike.

## The evidence (`evidence`)
- **`cutoff_utc`:** the as-of cutoff the request gave, if any. Under a cutoff, only what was published and available by
  it may be used.
- **`observations`:** each value retrieved by a tool, with:
  - **`label`:** what the value is, as the tool recorded it;
  - **`definition`:** AEMO's definition of its series, or for a project-derived value its derivation;
  - **`source`:** its evidence ID, the source rows (with their tables, files and times) and the source URLs;
  - **`availability`:** when it was published and available, and under a cutoff whether it was available by it.
- **`computed_results`:** each computed result, with:
  - its status, value (a maximum, or the highest value held when no maximum is established) and interval(s);
  - its coverage, limitations and source rows;
  - the rows of its window: under a cutoff, every interval, with whether each row was eligible at the cutoff.
- **`numeric_claims`:** each number the interpretation states, with the evidence item it cites.
- **`cited_passages`:** each cited document passage, with its document, section, publication date, eligibility and
  text.

Use the labels and definitions when you judge what a value is. For example, a label says whether a value is dispatch
total demand or operational demand, and which revision of a half-hour it is. Use the availability evidence when you
judge what was public by a cutoff.

## Fill in

**`outcome`:** one of S, U, C, F or X. **X takes precedence over everything else:** an answer that shows incorrect
content is X, whether it is a fallback or not.
- **S, supplied:** a usable answer that is not a fallback and has a validated interpretation, and whose shown text
  gives the correct result.
  - **For a requested maximum:** the right value and interval(s), for the right measure, region and window.
  - **When the gold status is `not_established`:** it says no maximum is established (as of the cutoff), and gives the
    highest value held only as that.
  - **For the forecast-run question:** every gold item.
- **U, unavailable:** it says explicitly that the requested item cannot be supplied, and nothing stands in for it.
- **C, clarification:** it is sent back with a specific question.
- **F, facts only:** a facts-only fallback, or a report with no valid interpretation, that shows nothing incorrect.
  Never S, even when the computed answer is right.
- **X, incorrect shown:** anywhere in what was shown, the computed answer, the interpretation or a fallback's
  observations alike:
  - a wrong value or interval for the requested maximum;
  - another measure, window or region presented as the requested maximum;
  - a highest value held (not established) presented as the maximum;
  - an unadmitted result's value, or an observation, presented as the requested maximum or as verified;
  - an interpretation that contradicts the computed answer;
  - under a cutoff, a value not available by the cutoff used or presented as public by it;
  - for a question that must be sent back, a value presented as the answer to what it leaves open;
  - for the forecast-run question: a wrong value-and-time pair, or another forecast run presented as the one asked
    for.

**The other fields:**
- **`H2_manual`:** causal claims stated as fact without support, beyond what the validator caught.
- **`H4_manual`:** numbers presented as facts that do not match the evidence or gold, or cannot be traced to it,
  including counts and times in limitations.
- **`correct_result_shown`:** true or false. Does what was shown give the correct result, whatever the outcome? A
  fallback can show it. Leave it as `n/a` where it is marked so.
- **`unadmitted_or_observation_presented_as_maximum`:** true if any text presents an unadmitted result's value, or an
  independently retrieved observation, as the requested maximum, or implies a result was verified when it was not.
  Observations that are simply listed are fine.
- **`interpretation_contradicts_answer`:** true if the interpretation contradicts the computed answer. That includes
  another maximum, another interval, or "no maximum" against an established one. Leave it as `n/a` where it is marked
  so.
- **`gold_items`** (the forecast-run question): `correct` true or false, for each gold item.
- **`interpretation_note`:** is the interpretation consistent, appropriately hedged and useful? This note is reported;
  it does not decide the outcome. A contradiction or X does.
- **`note`:** anything else, including anything the definitions do not cover.

**Questions that must be sent back:** a question can be partly understood and still be sent back for what it leaves
open. That is the expected behaviour. What matters is that no value is presented as the answer to what it leaves open.

When done, report every file you read.
