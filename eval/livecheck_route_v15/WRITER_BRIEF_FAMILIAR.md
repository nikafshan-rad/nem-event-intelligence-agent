# Writer's brief, step 2: the reading of ten existing questions (D01–D10)

Your seven questions are fixed. Their output has been hashed and is not changed by this step.

Now give the reading of ten existing questions, as you did for your own:
- they are in `familiar/questions.json`, which was added to the kit only now;
- use the same rules as before (`CAPABILITIES.md` and `GOLD_FORMAT.md`);
- work only inside the kit.

**Each question carries the set the owner has designated for it:**
- **supply:** expected to be resolved;
- **containment:** expected not to be answered with demand forecasts;
- **ambiguity:** two outcomes are pre-registered.

Give your own reading in every case. If you judge that a question should not be handled as its set says, say so
plainly in `notes` and give the reading you judge correct. That disagreement is reported to the owner, and nothing is
changed to fit the set.

**D08 is the ambiguity case.** The owner has pre-registered two acceptable outcomes:
1. asking which forecast is meant (`clarify_which_forecast`);
2. reading it as a request about AEMO's operational demand forecasts.

Give `acceptable_outcomes` as those two. Fill in every field of the demand reading as you read the question:
- the operation;
- the scope and its bounds;
- the run selection;
- the cutoff;
- the anchors;
- tool eligibility.

D08's `outcome` is `clarify_which_forecast`. Its demand-reading fields are still filled in.

**D10 has a request field** (`as_of_utc`). A request field is authoritative.

**Output:**
- Write `out/familiar.json` in the form `{"cases": [ ... ]}`, with one record per question.
- Compute every UTC bound with code in `work/`.
- Add a section to `out/REPORT.md` for this step: the files you opened, the commands you ran, the same confirmation,
  and your judgement calls.
