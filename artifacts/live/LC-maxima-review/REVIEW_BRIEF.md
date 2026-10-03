# Review brief: the Live acceptance check of computed demand maxima

You are reviewing what an assistant showed for each question of a one-off check. It answers analysts' questions about
the Australian National Electricity Market from a pinned copy of public AEMO data.

Your sheet gives, for each answer:
- the question and its request fields;
- what was shown;
- the gold, the expected answer, which was computed and checked independently.

Fill in each answer's `fill` block. Read only your sheet and this brief. Two reviewers read every answer, and the
stricter reading prevails.

## What was shown
- **`computed_answer`:** statements rendered by code from a result that a runtime verifier checked. Each has a
  `status` and a `verification`. `not_verified` means the result was not admitted, and no value of it is given.
- **`summary`, explanations, findings, uncertainties, missing evidence:** the interpretation, written by the model and
  checked by a validator.
- **`label`, `interpretation` and `validation`:** whether the interpretation was validated, withheld because it failed
  validation (a facts-only fallback), or absent.
- **`observations`:** values retrieved by tools.

Read everything shown, the computed answer and the interpretation alike.

## Fill in

**`outcome`:** one of S, U, C, F or X.
- **S, supplied:** a usable answer that is not a fallback and has a validated interpretation, and whose shown text
  gives the correct result.
  - For a requested maximum: the right value and interval(s), for the right measure, region and window.
  - When the gold status is `not_established`: it says no maximum is established (as of the cutoff), and gives the
    highest value held only as that.
  - For a regression control: every gold item.
- **U, unavailable:** it says explicitly that the requested item cannot be supplied, and nothing stands in for it.
- **C, clarification:** it is sent back with a specific question.
- **F, facts only:** a facts-only fallback, or a report with no valid interpretation. Never S, even when the computed
  answer is right.
- **X, incorrect shown:** anywhere in what was shown:
  - a wrong value or interval for the requested maximum;
  - another measure, window or region presented as the requested maximum;
  - a highest value held (not established) presented as the maximum;
  - an unadmitted result's value, or an observation, presented as the requested maximum or as verified;
  - an interpretation that contradicts the computed answer;
  - for a question that must be sent back, a value presented as the answer to what it leaves open;
  - for a regression control: a wrong value-and-time pair, another forecast run presented as the one asked for, or a
    value given in place of one that was not public by the cutoff.

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
- **`gold_items`** (regression controls): `correct` true or false, for each gold item.
- **`interpretation_note`:** is the interpretation consistent, appropriately hedged and useful?
- **`note`:** anything else, including anything the definitions do not cover.

When done, report every file you read.
