# Reconciling a held-out disagreement (pre-registered texts)

Used only for a held-out question on which `gold.py --compare` finds a gated item where the writer's record and the
reviewer's blind record disagree (`PROTOCOL.md`, "The gold"). The developer passes these texts unchanged, with the
one question's records, and decides nothing.

## Step 1, to the writer
> For question {config}, an independent reviewer read the question without seeing your record. Their record is below,
> together with the gated items on which it differs from yours. Re-read the question and `CAPABILITIES.md`. Then
> either revise your record (give the whole revised record), or keep it and explain why in one paragraph. Do not change
> the question. Work only in your kit.

## Step 2, to the reviewer
> For question {config}, the writer's final record is below. Re-read the question and `CAPABILITIES.md`. Answer
> `accept` if you judge the record a correct reading of the question under `CAPABILITIES.md` (its acceptable outcomes
> included), or `reject` with one paragraph saying why. Work only in your kit.

## Step 3, if rejected, to the writer
> Question {config} stays in disagreement and is replaced. Write one new question of the same family that meets the
> brief's row for {config}, with its record, in your own words; run the overlap checker on it. Do not reuse the
> question's wording. Give the new record.

The new question goes to the reviewer blind (its question and request fields only), and is compared as before. If it
is still in disagreement, it is dropped, and the shortfall is recorded in `PROVENANCE.md`.
