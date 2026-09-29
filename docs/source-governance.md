# Source governance: how publisher changes are caught, reviewed and recorded

This page is for the person who reviews data changes. It explains in plain terms what happens when AEMO or NASA
changes a file this project relies on, and what you need to do.

## The rule

The application and its evaluation use **only the exact source versions a reviewer approved**. Every version is
pinned by a SHA-256 hash in `data/source_selection.json`. If a publisher changes a file, the new version is **not**
used until a reviewer accepts it. Nothing switches over silently.

## Two separate checks

| | Pinned build (`ci` workflow, `make restore-pinned` / `make data` / `make index`) | Publisher-refresh check (`publisher-refresh` workflow, `make refresh-check`) |
| --- | --- | --- |
| When | Every push and pull request | Weekly (Monday 19:17 UTC), on demand, and on pull requests that touch governance code |
| Uses | Only approved bytes from the store whose hash matches the pin; no publisher is contacted | Whatever the publishers serve today |
| If a publisher changed a file | Nothing changes: the approved bytes come from the store | Reports the change for review, with a diff |
| Changes the pins? | Never | Never |

The pinned build restores every approved file from the **approved-bytes store**, which is content-addressed by
SHA-256 and held in this private repository's releases (docs/pinned-store.md). It then checks that no publisher was
contacted. Without access to the store, for example on a machine without read access to this repository, `make data`
and `make index` download from the publishers and verify every file against its pin. Those builds see roll-off and
revisions (see "What the application shows"). The GitHub Actions cache holds only the embedding model; it is not an
archive, because GitHub deletes a cache after 7 days without use.

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
4. Add the newly approved bytes to the store: `python scripts/publish_pinned_store.py --release pinned-bytes-<date>
   --target <commit>`. This creates a new release; nothing existing is replaced. The old version stays in the store
   as a `superseded` object.
5. Publish and register a new verified bundle: `python scripts/publish_store_bundle.py --release
   pinned-bytes-bundle-<date>`.
   - It takes every current pin's approved bytes from the store (never from a publisher) and checks each against its
     key and its pin.
   - It publishes one archive to a new release, downloads it back and checks it, and only then records it under
     `bundles` in `data/pinned_store.json`.
   - **This step is required.** `make store-verify`, and therefore CI, fails while any current pin is in no bundle.
     CI restores only through bundles to stay within the API quota (`docs/pinned-store.md`, "Bundles").
6. Rebuild with `make restore-pinned` / `make data` / `make index` and refresh the committed results (`make eval`,
   `make retrieval-eval`, `make demo`).
7. Open a pull request with `data/source_selection.json`, `data/SOURCES.md` and `data/pinned_store.json`. CI:
   - checks the history entry;
   - checks that the store index and its bundles were only added to;
   - checks that every current pin is in a bundle;
   - runs everything against the new pins from the store.

If you do not accept a change, do nothing. Pinned builds keep restoring the approved version from the store.

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

## What is kept, and where

- **Every approved version**, current and superseded, is in the approved-bytes store (docs/pinned-store.md). This
  includes SO_OP_3705 Version 97, recovered and verified from the 2026-09-23 CI cache, and all 198 pinned market
  notices, including the 67 NEMWeb no longer serves.
- **AEMO's terms** permit use "for any purpose" with attribution (archived page, 2026-09-23; see docs/pinned-store.md).
  NASA POWER states no restriction and asks for acknowledgement and notification. The store is private.
  Publisher files are still not committed to git (D2), for size and separation.
- **The GitHub Actions cache is not an archive.** It holds only the embedding model.
- **Market notices** leave NEMWeb `Reports/Current` after about 60 days. NEMWeb has a `Reports/Archive/Market_Notice/`
  directory, but its listing contained no files when checked on 2026-09-27. Builds that download from NEMWeb, rather
  than from the store, look there for every missing notice (accepting only a hash match) and record what they saw.
- **Not stored:** the embedding model (Hugging Face, pinned by revision) and Python packages (pinned in
  `requirements.lock`). Builds depend on those two services being available.
