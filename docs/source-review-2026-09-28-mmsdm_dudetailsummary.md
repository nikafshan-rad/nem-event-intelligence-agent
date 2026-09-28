# Source review: `mmsdm_dudetailsummary` revised upstream (2026-09-28)

**Status: reviewed. Recommendation: keep the current pin in PR #5, and propose an approved re-pin separately.**
- No pin, data file or evaluation data was changed by this review.
- `publisher-refresh` keeps reporting REVIEW NEEDED until a reviewer decides.

## What the refresh check found

- **Workflow:** `publisher-refresh` run 36404746941 (commit `f3b2822`), report `20260928T094009Z`.
- **Overall:** checked 307, unchanged 232, **changed 1**, unavailable 74 (0 unexpected).

| | Pinned | Current at the publisher |
| --- | --- | --- |
| SHA-256 | `164946e00925fcbc177c3fb0e59585769df4b178e09b682b5affb913738415a8` | `3a8f90acf3977952f19051dfac68a1370229d709cb654754f698c41017c3d63f` |
| Size | 378,894 bytes (CSV member 5,082,018 B) | 379,041 bytes (CSV member 5,083,915 B) |
| Last-Modified | Fri, 11 Sep 2026 06:18:00 GMT | Mon, 28 Sep 2026 02:31:42 GMT |
| File header (C row) | generated 2026/09/08 13:56:48 | generated 2026/09/25 13:40:25 |

URL: `…/MMSDM_2026_08/MMSDM_Historical_Data_SQLLoader/DATA/PUBLIC_ARCHIVE#DUDETAILSUMMARY#FILE01#202608010000.zip`
(AEMO's August 2026 monthly archive of unit registration details).

- The candidate was fetched once from that URL for this review, into a scratch directory rather than the data
  directory. It hashes to the report's `3a8f90ac…c63f`.
- The pinned file in `data/raw` hashes to its pin.

## Substantive content difference (rows keyed by DUID and START_DATE, all columns except LASTCHANGED)

- **Same columns:** 23,340 rows pinned; 23,348 in the candidate.
- **23,331 rows differ only in `LASTCHANGED`.** The archive was re-issued: the candidate stamps almost every row
  2026/09/24 11:50:44. This is what the whole-file line diff (23,339 removed, 23,347 added) was showing.
- **8 registration rows added, all effective from September 2026:**

  | DUID | Start date | Region | Dispatch type |
  | --- | --- | --- | --- |
  | JEMALNG1 | 2026-09-11 | NSW1 | semi-scheduled generator |
  | TB3B1 | 2026-09-15 | SA1 | bidirectional |
  | WOORB1 | 2026-09-15 | VIC1 | bidirectional |
  | TEMPB1 | 2026-09-18 | SA1 | bidirectional |
  | VSNEL2S1 | 2026-09-22 | NSW1 | non-scheduled load |
  | VSVEL2S1 | 2026-09-22 | VIC1 | non-scheduled load |
  | SNB01 | 2026-09-25 | QLD1 | bidirectional |
  | SNB02 | 2026-09-25 | QLD1 | bidirectional |

- **6 rows closed:** the `END_DATE` of the previous record for TEMPB1 (from 2026-08-28), SNB01, SNB02, JEMALNG1,
  VSNEL2S1 and VSVEL2S1 (from 2026-07-01) changes from open-ended (2999-12-31) to the start date of its new record in
  September.
- **Nothing removed; no region, dispatch type or loss-factor value changed** for any period before 2026-09-11.

## What it affects in this project

- **Data table:** `duid_region` (23,340 rows), built from this file. No event, document or evaluation case is fed by
  it (report "Feeds": events none, evaluation cases none).
- **Code:** only `get_generation_change` reads the table. It joins each 5-minute SCADA interval to the registration
  row valid at that interval (`valid_from_utc` < interval ≤ `valid_to_utc`).
- **Effect:** every analysed window lies in late July to August 2026, and the last event is 20 August. None of those
  joins can reach a row that starts on or after 2026-09-11, and each closed record is still valid through August. **No
  tool output for any event changes.**
- **Versions:** re-pinning changes the **data version** (`8c14c217f5570d32` → `3765460daa3fb5c0` in the sandbox)
  because the table's contents change. The corpus version is unchanged.

## Pinned versus candidate offline evaluation (sandbox, Replay only; from the refresh report)

| | Pinned | Candidate |
| --- | --- | --- |
| Data / corpus version | 8c14c217f5570d32 / 221b6ea0f21e006d | 3765460daa3fb5c0 / 221b6ea0f21e006d |
| Index chunks | 597 | 597 |
| Gate checks all true | yes | yes |
| Status ok (test) | 20/21 | 20/21 |
| Gold numbers / forecast / citation | 13/13, 5/5, 3/4 | 13/13, 5/5, 3/4 |
| As-of leaks | 0 | 0 |
| Retrieval Recall@5 / Hit@5 / MRR | 16 / 15 / 0.83 | 16 / 15 / 0.83 |

Cases whose result changes: **none**.

## Recommendation

**Keep the current pin in PR #5**, and treat the re-pin as a separate, explicitly approved change after PR #5 is
reviewed. Why keep it now:
1. The revision is a republication plus registrations effective from 11 September 2026, after every analysed window.
   No answer, tool output or evaluation result changes.
2. Every Replay and Live result recorded in PR #5 cites data version `8c14c217f5570d32`. Re-pinning mid-review would
   change the data version under those records for no analytical benefit.
3. The pinned bytes remain in the approved-bytes store, so CI and collaborators keep reproducible builds.

Why re-pin afterwards rather than never:
- The publisher no longer serves the pinned bytes at this URL. A fresh setup **without** access to the approved-bytes
  store would fail this file's checksum and exclude `duid_region`. The generation-change tool would then report that
  data as unavailable.
- Re-pinning restores public reproducibility. The current version would also be kept in the store with its approval
  history.

**Proposed approved re-pin**, for a separate PR and only after reviewer approval:

```
python scripts/repin_source.py --source-id mmsdm_dudetailsummary \
    --expect 3a8f90acf3977952f19051dfac68a1370229d709cb654754f698c41017c3d63f \
    --report <that run's artifacts/source_refresh/<run>/report.json> --approved-by <reviewer> \
    --publisher-revision "AEMO re-issued the Aug-2026 DUDETAILSUMMARY archive on 2026-09-25: LASTCHANGED restamped; 8 registrations added and 6 closed, all effective from 2026-09-11" \
    --reason "No effect on any analysed window (last event 2026-08-20); restores public reproducibility"
```

In that PR, record the new data version, and re-run the Replay evaluation and the safety suite on it.
