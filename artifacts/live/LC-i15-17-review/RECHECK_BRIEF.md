# Recheck brief: the same 18 answers, now with the exact questions

Your first review (`out/REVIEW.json`) was made without the question texts. `QUESTIONS.json` now gives the exact
frozen question and request-level fields of each case. K07, for example, carries a request-level `as_of_utc`
cutoff that is not in its question text.

**Unchanged:**
- **The answers:** none was regenerated.
- **The rules:** `PASS_RULE.md` and `REVIEW.md`.
- **The gold:** `GOLD.json` and `DEVCHECK.json`.
- **Your original review:** `out/REVIEW.json` stays as it is (it is read-only), and is kept as your original
  judgement.

## What to do

1. **Recheck every case:**
   - Read the question and request, then the shown answer (`SHEET.json`), against the same rules and gold.
   - Decide again each case's outcome (S, U, C, F or X), each gold item's checks, and H2 and H4.
   - Pay attention to what the question asked: the measure, the interval and how it is named, the window, which
     forecast run, and any cutoff. Ask whether the answer's labels ("highest", "extreme", "final run", directions)
     are right for what was asked.
2. **Write `out/REVIEW_with_questions.json`:**
   - the same format as `out/REVIEW.json`;
   - `"reviewer": "independent reviewer (agent), recheck with the exact questions"`;
   - every case's `fill` completed.
3. **Write `out/REVISIONS.json`:**

   ```json
   {"cases": [{"case_id": "K01", "changed": true|false,
               "changes": [{"field": "outcome|H2_manual|H4_manual|items[i].<check>", "original": ..., "revised": ...,
                            "reason": "<why the question changes the judgement>"}]}]}
   ```

   Include every case; `changes` is empty when nothing changed.

Independence rules as before: read and run only what is inside this kit, open nothing else on this machine, and do
not use the web. In your final message, list the files you read and the commands you ran, and each revision with
its reason. Do not paste whole answers.
