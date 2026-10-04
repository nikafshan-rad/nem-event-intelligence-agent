# What the assistant supports (for a routing check)

This describes, in plain terms, what an analyst's assistant for the Australian National Electricity Market (NEM) can
do. You use it to decide what each question means and what the assistant should do with it. It is not the
assistant's instructions and not its code; you have no access to those, and you do not need them. Where this text
does not settle a reading, use your own judgement as a careful analyst and explain it.

## The market and its time zones
- **Regions:** NSW1 (New South Wales; Sydney time), QLD1 (Queensland; Brisbane time, no daylight saving), SA1
  (South Australia; Adelaide time), TAS1 (Tasmania; Hobart time), VIC1 (Victoria; Melbourne time). A capital city
  names its region (Sydney → NSW1, Brisbane → QLD1, Adelaide → SA1, Hobart → TAS1, Melbourne → VIC1). Western
  Australia and the Northern Territory are outside the NEM.
- **Times:** AEST is UTC+10; AEDT is UTC+11; ACST is UTC+09:30; ACDT is UTC+10:30. The data covers July and August
  2026, when there is no daylight saving (AEST and ACST), and some of October 2025, when NSW1, VIC1 and TAS1 are on
  AEDT, SA1 on ACDT, and QLD1 stays on AEST.
- **Half-hours** are named by their end: "the half-hour ending 18:00" is (17:30, 18:00]. A **local day** runs from
  local midnight to the next local midnight in the region's time zone.

## The investigations it runs
- **Market event review:** what happened around a high- or low-price interval in a region on a date (prices, demand,
  generation, published notices, observed weather context).
- **Forecast review:** AEMO's issued **operational demand** forecasts: what they said, and how they compared with
  actual operational demand.
- **Source explanation:** what a term, procedure or AEMO notice says.

## AEMO operational demand forecasts: the only forecasts it provides
- AEMO issues **forecast runs**. Each run is issued at a time and gives, for each half-hour ahead, POE10, POE50 and
  POE90 values of operational demand (MW). A run becomes public some time after it is issued.
- **What can be asked (the operation):**
  - **forecast value:** what a forecast said (its values, or which run it was), not compared with actual demand;
  - **single-interval comparison:** a forecast and actual operational demand for one half-hour (also when the
    question asks for both values without an error figure);
  - **window comparison:** forecasts compared with actual demand over a period (accuracy, error, misses).
- **What it is asked about (the scope):**
  - one half-hour;
  - a price event's **peak half-hour** (the half-hour containing the event's peak five-minute price interval);
  - a **whole local day**, when a date names the day analysed;
  - a price **event's window**;
  - an **explicit period** the question states, with its start and end.

  A period must be made of whole half-hours and last at most 24 hours. A longer period cannot be served: it is sent
  back, never cut short.
- **Which run (the run selection),** when the question asks for one specific run:
  - **last_issued_before:** the last run issued before the target half-hour starts, however it is worded;
  - **issued_at:** the run issued at a time the question states;
  - **as_of_availability:** with an as-of cutoff, the newest run that was public by the cutoff.

  When no single run is asked for, the run selection is **none**.
- **An as-of cutoff** ("as of", "known at", "published by", "looking only at what was public at" a time) limits what
  was public. It must come from the question's words or from the request field `as_of_utc`, which is authoritative,
  and be pinned to an exact UTC instant. A cutoff that cannot be pinned down is sent back. A cutoff does not change
  which half-hour or period is asked about, and it does not replace the run selection.
- **Dates:** a question names the date it is about once. A question naming two or more calendar dates is sent back to
  ask which date is meant (an exact timestamp such as `2026-07-30T18:56:59Z` is a time, not a named date). A
  half-hour given by clock times alone, in a question naming no date, is dated by an exact as-of cutoff when it falls
  after the cutoff on the cutoff's own date in that half-hour's time zone; otherwise its date is missing.

## Demand maxima
It can find when, and at what level, a demand measure was highest over a window, from actual data:
- **the measure:** operational demand, or dispatch total demand (TOTALDEMAND);
- **the window:** a whole local day, a price event's window, or an explicit window;
- **an optional cutoff:** as above.

A demand maximum can be the request of a forecast review or of a market event review: a question about a price event
that asks when, or how high, a demand measure peaked is a demand-maximum request within that event review. "Demand"
alone does not say which measure: such a question must be sent back to ask which measure is meant.

## Request fields
A question may come with request fields, which are authoritative:
- **`as_of_utc`:** the as-of cutoff, an exact UTC instant. It applies even when the question's own cutoff words cannot
  be pinned down, or name a different time; the difference is noted with the answer.
- **`window_start_utc` and `window_end_utc`:** the exact window of the analysis (for a demand maximum, the window it
  is taken over; for a forecast comparison, the period compared).
- **`region`**, **`event_date`** and **`intent`**, when given, are used as given.

## What it does not provide
- **No forecast of any other kind:**
  - weather, including temperature, wind or solar;
  - prices, including AEMO's predispatch price forecasts;
  - anything else, such as reserve, generation or interconnector-flow forecasts as values.

  Recognising such a request adds no capability. It must never be answered with operational demand forecasts or
  their values instead.
- **No predictions, trades, bids or advice.**
- A market event review may describe **observed** weather. That is not a weather forecast.

## How a question should be handled
There are four outcomes:
- **`resolved`:** the assistant proceeds with one supported request (an operational demand forecast request, or a
  demand-maximum request), every detail pinned down exactly as asked;
- **`clarify`:** the question is sent back, asking for what is missing or which request is meant; nothing proceeds;
- **`refusal`:** refused as out of scope;
- **`event_review_without_demand_forecast`:** the question is handled as a market event review that uses no demand
  forecast, and says that the forecast part is not answered (or that a forecast is mentioned without showing which).

How each kind of question should be handled:
- **A supported request** with every needed detail pinned down is `resolved`, with its details exactly as asked. The
  assistant never substitutes another kind of forecast, run, half-hour, operation or period.
- **A request for another kind of forecast only** is not answered with demand forecasts: `clarify`, `refusal` and
  `event_review_without_demand_forecast` are all acceptable.
- **A forecast whose kind the question does not show,** where demand, price or weather are all plausible, is not
  assumed to be demand: `clarify` or `event_review_without_demand_forecast`.
- **A question asking for an operational demand forecast and also for another kind:**
  - the demand request is `resolved` when its own words give its operation and scope unambiguously, and the other
    request is then named as not answered (a **not-answered part**);
  - otherwise the question is sent back (`clarify`).
- **Declined requests** ("not the weather forecast", "leaving aside the demand forecasts") and **background** (a
  statement reported from elsewhere, in quotation marks or not, or a forecast mentioned only to explain something) are
  not requests.
- **Two distinct supported requests in one question** (for example an operational demand forecast comparison and a
  demand maximum, two measures' maxima, or forecasts over two different periods): the assistant answers one request
  at a time and never chooses between them, so the question is sent back to ask which is meant (`clarify`).
  - **The one exception:** a question asking for a forecast's values and for the actual value of the **same
    half-hour**, under the **same named run** and the same cutoff, is one single-interval comparison, which carries
    both values.
  - Answering one request and leaving the other unmentioned is never acceptable.
- **Times the assistant cannot pin down** are sent back, never guessed: "noon", "midday", parts of the day ("in the
  morning"), a period over 24 hours for a forecast comparison, a half-hour without its start or end ("the 18:30
  half-hour"), and a clock time with no time zone.
- **Tool eligibility:** whether the assistant should use its operational-demand forecast tools:
  - **eligible:** for a resolved operational-demand forecast request;
  - **not_used:** for any other question that asks for a forecast;
  - **not_restricted:** when the question asks for no forecast at all. A declined or background forecast is not asked
    for.
