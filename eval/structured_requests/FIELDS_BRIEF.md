# Brief: write the routing decision a careful model would return for 60 questions

You are writing development test material for a research assistant about Australia's National Electricity Market
(NEM). Its first step, "routing", reads an analyst's question and returns one JSON object, the routing decision. Its
instructions are in `ROUTING_INSTRUCTIONS.md`, and its exact JSON schema is in `route_schema.json`.

For each of the 60 cases in `matrix.json`, write the routing decision that a careful model would return if it followed
`ROUTING_INSTRUCTIONS.md` exactly. Each case gives:
- the question;
- any request fields (these come with the question from the user; they are not part of the routing decision);
- an `expected` block, written by another author, describing the request the question expresses.

Use `expected` as the reference for what is correct, but follow the instructions when you write the routing decision.
`DATA.md` and `data/events.json` describe the data period, the regions and the eight price events.

## What to write for each case

A full routing decision matching `route_schema.json`:
- **The core fields:** `intent`, `region`, `event_date`, `as_of_utc`, `needs_clarification`, `clarification_reason`,
  `clarification` and `out_of_scope`.
- **`requested`,** with its `forecast_run` and `maximum` parts.
  - **Copied words:** every `*_text` field is copied **character for character** from the question, including
    punctuation, capitals and dash style. If you cannot copy exact words that support a field, leave that `*_text`
    field null.
  - **Times:** every time is ISO-8601 UTC ending in `Z`, converted by you from the question's own words, carefully.
  - **Unknowns:** where the question leaves a value unstated or ambiguous, follow the instructions: leave it null (or
    use `unclear` / `unspecified`). Never guess a date, a time zone, or whether a time is the start or the end of a
    half-hour.
  - **Questions with neither request:** `forecast_run.selection` is `none` and `maximum.kind` is `none`, and the other
    `requested` fields are null.

## Output

Write `out/fields.json`:

```json
{"version": "structured-requests-fields-1", "authored_by": "independent field writer (agent)", "generated_at": "<UTC>",
 "matrix_sha256": "<SHA-256 of matrix.json>",
 "cases": [{"id": "P01", "route": { ...a complete routing decision... }, "note": "<anything a reviewer should know>"}]}
```

Before you finish, check that:
- every `route` validates against `route_schema.json`;
- every non-null `*_text` value occurs verbatim in its question;
- there are 60 cases, P01–P60 in order.

Use any tools you like inside this kit, for example the Python standard library with `json`.

## Independence rules (important)

- Read and run only what is inside this kit directory. You may create `work/` for your own scripts.
- Do **not** open, list or search anything else on this machine, in particular anything under `/workspaces` or `/tmp`
  outside this kit, or your home directory. Do not use the web.
- In your final message, list the files you read and the commands you ran, the number of cases per `selection` and
  per `maximum.kind`, and any case where you were unsure. Do not quote questions.
