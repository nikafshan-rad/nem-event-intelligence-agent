# Source governance: how publisher changes are caught, reviewed and recorded

This page is for the person who reviews data changes. It explains in plain terms what happens when AEMO or NASA
changes a file this project relies on, and what you need to do.

## The rule

The application and its evaluation use **only the exact source versions a reviewer approved**. Every version is
pinned by a SHA-256 hash in `data/source_selection.json`. If a publisher changes a file, the new version is **not**
used until a reviewer accepts it. Nothing switches over silently.

## Two separate checks

| | Pinned build (`ci` workflow, `make data` / `make index`) | Publisher-refresh check (`publisher-refresh` workflow, `make refresh-check`) |
| --- | --- | --- |
| When | Every push and pull request | Weekly (Monday 19:17 UTC), on demand, and on pull requests that touch governance code |
| Uses | Only bytes whose hash matches the pin | Whatever the publishers serve today |
| If a publisher changed a file | The source cannot be obtained in its pinned form, so it is excluded and reported (see "What the application shows"). For documents, `make index` fails. | Reports the change for review, with a diff |
| Changes the pins? | Never | Never |

The pinned build fetches from the publishers and verifies every file. A GitHub Actions cache saves repeat
downloads, but it is only a convenience: GitHub deletes a cache after 7 days without use, so it is **not** an
archive (see "What we cannot keep").

A pull request that changes a pin is also checked by `scripts/check_pin_changes.py`: every changed hash must come
with a history entry naming the reviewer and the reason, made with `scripts/repin_source.py`.

## What the refresh report tells you

`make refresh-check` downloads every pinned source again into `artifacts/source_refresh/<run>/candidates/`. That
folder is separate from the files the application uses and is never committed. The command then writes
`report.md` (for you) and `report.json`. For each source the result is one of:

- **unchanged**: the publisher serves exactly the pinned content.
- **changed**: the publisher serves different content. The report shows:
  - the source ID, URL and retrieval time;
  - old and new hashes;
  - for documents, the version or effective date where the document states one;
  - for NASA POWER, the API version and data sources (for example provisional GEOS-IT versus final MERRA-2);
  - a **content diff**: the PDF or HTML text lines added and removed, each changed NASA value with its largest
    change, or the changed members of a zip file. A diff needs the old bytes on the machine running the check;
    otherwise the report says so;
  - which **data tables** (with row counts) and **index documents** (with chunk counts) the source feeds, and which
    events and evaluation cases rely on it;
  - with `--eval` (what `make refresh-check` runs), the **evaluation differences**: the pinned set and the
    candidate set are each built and evaluated offline in separate sandboxes, and the report compares their held-out
    metrics, retrieval scores and any case whose result changes. No hosted model is called;
  - the exact command to accept the change.
- **inconsistent** (API sources only): the publisher returned the pinned content to some requests and other values
  to others. This happened with NASA POWER on 2026-09-27. It needs watching, not accepting.
- **unavailable**: the publisher did not serve the file.
  - For NEMWeb `Reports/Current` files (market notices and daily files) this is expected rolling retention.
  - Anything else is flagged as unexpected.

The command exits with 1 ("REVIEW NEEDED") when there is a changed source or an unexpectedly unavailable one.

No credentials are used. Reports record only public URLs and four response headers (`Last-Modified`, `ETag`,
`Content-Length`, `Content-Type`).

## Accepting a new version (explicit reviewer action)

1. Read the report. Check that the change is a genuine publisher revision, what changed, and whether the
   evaluation differences are acceptable.
2. Run the command printed in the report, filling in your name and reasons:

   ```bash
   python scripts/repin_source.py --source-id aemo_so_op_3705 --expect <new hash from the report> \
       --report artifacts/source_refresh/<run>/report.json --approved-by "Your Name" \
       --publisher-revision "Version 98, effective 23 September 2026 (was Version 97)" \
       --reason "AEMO replaced the procedure; the changes do not affect the definitions we cite"
   ```

   The script refuses if:
   - the report does not list that change;
   - the publisher no longer serves exactly the reviewed content;
   - the file is not what it should be (for example, not a PDF).
3. The old pin is kept in the source's `superseded` history, with its hashes, dates, the publisher's version
   details, the report reference, your name and your reason. `data/SOURCES.md` shows the history.
4. Rebuild with `make data` / `make index` and refresh the committed results (`make eval`, `make retrieval-eval`,
   `make demo`).
5. Open a pull request. CI checks the history entry and runs everything against the new pins.

If you do not accept a change, do nothing. The application keeps using the pinned version while this machine or
the CI cache still has it. Once it cannot be obtained, the source is shown as excluded.

## What the application shows

The API's `/health` and `/sources` endpoints, the Streamlit sidebar ("Data and sources") and `nem-agent sources`
show the data and corpus versions and place every pinned source in one of three groups:

- **pinned**: the approved version is in use, verified by its hash.
- **revised**: the publisher now serves something else.
  - If a verified copy of the approved version is still available, it stays in use and is marked "review
    pending".
  - Otherwise the source is excluded.
- **unavailable**: the publisher does not serve it and no verified copy exists, so the source is excluded.

Excluded sources are never replaced by other content. Tools report them as missing evidence, and answers abstain
or state the gap. For example, a missing weather source is named with its status, and event reports say how many
of the selected market notices are missing.

## What we cannot keep

- **Publisher files are not redistributed.** AEMO's copyright terms could not be confirmed (docs/decisions.md D2),
  so the repository contains hashes and metadata, not the files.
- **Superseded versions** are kept only on the machine that held them when they were re-pinned, in
  `data/pinned_store/` (git-ignored). If AEMO replaces a document, other machines can no longer obtain the old
  version, and the history records only its hash and details. SO_OP_3705 Version 97 was lost this way: it was
  re-pinned on 2026-09-25, before this workflow existed, and the next `make index` overwrote the local copy.
- **The GitHub Actions cache is not an archive.** It holds the pinned files for up to 7 days without use.
- **Market notices** leave NEMWeb `Reports/Current` after about 60 days. NEMWeb has a `Reports/Archive/Market_Notice/`
  directory, but its listing contained no files when checked on 2026-09-27. The build looks there for every missing
  notice (accepting only a hash match) and records what it saw.

A durable, private store of the pinned bytes would make every build fully repeatable. Whether AEMO's terms allow
that is a decision for the project owner.
