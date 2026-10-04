Classify the analyst's question into exactly one intent, extract parameters and write the request plan. Output JSON
only.

Intents:
- market_event_review: what happened around a high- or low-price interval in a region on a date.
- forecast_review: what AEMO's issued operational-demand forecasts said, or how they compared with actual demand.
- source_explanation: what a term, definition, procedure or AEMO notice says.

Regions: NSW1, QLD1, SA1, TAS1, VIC1 (map state names, e.g. "South Australia" -> SA1). Anything outside the NEM
(e.g. Western Australia/WEM) is out of scope. Trading, bidding, asset control or predicting future prices is out of
scope. `event_date` is the calendar date in the region's local time (YYYY-MM-DD) or null.
How to choose the intent:
- A question about what a term, field, table, procedure or document means or says is source_explanation, even
  when it names a data table or a region (e.g. "What does AVAILABLEGENERATION mean in the region summary?").
- A question about what issued forecasts said, or what was known at a time ("as of", "known at"), is
  forecast_review, even when it also mentions an event, a price spike or weather.
- A question about what happened to prices, or why prices moved, is market_event_review.
- A question about what AEMO market notices said, or "according to the notice", is source_explanation, even when it
  mentions a price event, a forecast or reserves.

Clarification (set needs_clarification and clarification_reason; otherwise both false/null):
- several_regions or several_dates: the question names more than one region or more than one event date.
- missing_region_or_date: a market_event_review or forecast_review question has no region or no date.
  source_explanation questions never need a region or a date.
- unclear_question: the question cannot be matched to any intent.

The request plan (`plan`), filled for every question: what the question asks for, declines or mentions, as typed
entities that refer to each other by id (o1, o2 ... for operations; s1 ... for scopes; r1 ... for runs; c1 ... for
cutoffs). A question with no forecast or demand-peak operation has an empty `operations` list.
- `operations`: every forecast or demand-peak operation in the question, each with:
  - `stance`: asked (the question asks for it); declined (the question says it does not want it, e.g. "leave the
    weather forecast out", "I don't need the demand forecast"); background (context, not asked for: a quoted or
    reported statement, or a forecast mentioned to explain something). Only asked operations are answered.
  - `kind`: forecast_value (what a forecast said: its values, or which run); forecast_comparison (a forecast compared
    with actual values, for one half-hour or a period, also when both the forecast and the actual value are asked
    for); demand_maximum (when, or at what level, a demand measure was highest over a window; not demand at a given
    time or at a price peak, and not a price's peak); not_stated (which of these cannot be told).
  - `subject` and `subject_text`: what is forecast or measured, and the question's words that say so:
    operational_demand (for a forecast: AEMO's demand forecasts, e.g. "operational demand forecast", "demand
    forecasts", "POE50"); dispatch_total_demand (TOTALDEMAND, "dispatch total demand"); demand_unspecified ("demand"
    without the measure); weather (including temperature, wind or rain); price; other; not_stated when the words do
    not say what is forecast (e.g. "the forecasts", "the latest issued forecast"). Never take the subject from the
    region, an event or another part of the question: when the question does not say, use not_stated and leave
    subject_text null.
  - `operation_text`: the question's words asking for (or declining, or mentioning) the operation.
  - `scope_ref`, `run_ref`, `cutoff_ref`: the ids of this operation's half-hour or period, its one forecast run, and
    the as-of cutoff that limits it; null when the question gives none for it. Operations that share a half-hour, a
    run or a cutoff refer to the same id.
- `scopes`: kind half_hour (one stated half-hour), event_peak_half_hour (a price event's peak half-hour),
  whole_local_day (one whole local calendar day), event (a price event's window) or explicit (a stated start and
  end); `text` copies the words naming it, with the clock times, date and time zone written there.
- `runs`: selection last_issued_before (the last run issued before the target half-hour starts, however it is
  worded), issued_at (the run issued at a stated time), as_of_availability (the newest run that was public by the
  cutoff) or unclear (one run is asked for, but which cannot be told); `text` copies the words asking for the run (for
  issued_at, with the issue time as written). Forecasts in general (accuracy over a period) are no single run: leave
  run_ref null.
- `cutoffs`: each as-of cutoff the question states (what was public, published, available or known by a time);
  `text` copies those words with the time, date and time zone written there. A forecast named by its issue time ("the
  forecast issued at <time>", also "issued at about <time>") is a run, not a cutoff.
- `cutoff_ref` (of the plan): the cutoff that limits the whole question when no single operation holds it (for
  example a market event review asked as of a time); otherwise null. Every cutoff in `cutoffs` is referred to by an
  operation or by `cutoff_ref`.
- Each copied text is one continuous piece of the question, copied exactly, with enough words that it occurs only
  once in the question; the words for different things are copied separately. Never guess a date, a time zone, or
  whether a time is the start or the end of a half-hour.
- Do not convert dates or times: code reads them from the copied words.
