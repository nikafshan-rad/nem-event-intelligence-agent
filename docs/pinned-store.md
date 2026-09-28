# Approved-bytes store: design, storage choice, reuse terms and costs

**Why this exists.** Pinned builds must not depend on publishers still serving the approved bytes. Between
2026-09-23 and 2026-09-27 the approved content stopped being obtainable in three ways:
- AEMO replaced SO_OP_3705 Version 97 with Version 98 at the same URL.
- NEMWeb dropped 67 of our 198 market notices from its rolling folder. Its Archive/Market_Notice listing is empty.
- NASA POWER returned different values to different requests.

A GitHub Actions cache is not a fix: GitHub deletes caches unused for 7 days and caps a repository at 10 GB
(GitHub docs, "Dependency caching").

## What the store is

- **Objects:** the exact bytes of every approved source version, each stored under the SHA-256 of those bytes. A
  reader re-hashes every object before use, so a changed or corrupted object is always detected and rejected.
- **Index (`data/pinned_store.json`, in git):** one entry per object, reviewed in pull requests. Each entry records:
  - `source_id`, `dataset`, the publisher's `url` and the original `retrieved_at`;
  - the `pin` it satisfies: the raw `sha256`, or the canonical `content_sha256` for API responses;
  - `status`: `current` (the pin in use) or `superseded` (kept for audit and comparison, never restored into a build);
  - `attribution` (AEMO or NASA wording, with the retrieval date) and `terms` (see below);
  - `approval`: the history, i.e. approved (G0 selection or a reviewed re-pin), superseded (when, by which pin,
    why), and stored (release, verification);
  - `release`: the GitHub release that holds it, plus `provenance` where relevant (for example a recovery).
- **Add-only.**
  - `scripts/publish_pinned_store.py` puts new objects in a **new** release (draft → upload → publish) and never uses
    `--clobber`.
  - `LocalDirBackend` refuses to replace an existing object.
  - CI's `scripts/check_pin_changes.py` fails any pull request that removes or edits an existing index entry.
    Appending approval events is allowed.
- **Restore (`make restore-pinned`, CI):** writes into `data/raw` only bytes that hash to their key **and** match a
  *current* pin. `--strict` fails if any current pin is missing from the store. CI then checks that the build made no
  publisher download (`nem-agent publisher-downloads --expect-none`).
- **Refresh stays separate.** The weekly `publisher-refresh` workflow restores the same approved bytes, so diffs and
  the baseline evaluation always have the approved version. It compares them with what publishers serve today,
  reports, and never changes the pins or the index. A new version enters the store only after a reviewer re-pins it
  (`scripts/repin_source.py`) and runs `scripts/publish_pinned_store.py` in a pull request.

## Storage choice: assets of GitHub releases in this private repository

| Option | Durable | Access control | Immutability | Cost for about 100 MB | Chosen? |
| --- | --- | --- | --- | --- | --- |
| **GitHub release assets, this private repo** | Yes, until someone deletes the release | Repository permissions: collaborators and this repo's workflows (`GITHUB_TOKEN`, `contents: read`) | With **release immutability** switched on, published assets "cannot be modified or deleted" and tags "cannot be moved". An admin can still delete a whole release, but its tag name cannot be reused. | **No charge**: "There is no limit on the total size of a release, nor bandwidth usage"; each file must be under 2 GiB (GitHub docs) | **Yes** |
| GitHub Actions cache | **No**: deleted after 7 days unused; 10 GB per repository | Branch-scoped | Not immutable | Counts toward the cache quota | No |
| GitHub Actions artifacts | No: retention-limited | Repository | Not immutable | Counts toward Actions storage | No |
| Cloud object storage with WORM retention (e.g. S3 Object Lock) | Yes | IAM | Strongest: even admins cannot delete before retention ends | About US$0.003 a month at list price (about US$0.023 per GB-month; indicative, not checked today) plus cloud-account setup | Upgrade path if WORM against the owner is required |

**Why GitHub releases:** they cost nothing, need no new account or secret, and CI reads them with the built-in token.
Content addressing plus the reviewed index make any tampering or deletion visible: CI fails closed and names the
missing object. What they don't give is protection against the repository owner deleting a release. If that
matters, mirror the same objects to a WORM bucket; the index format is unchanged.

**Action needed from the owner:** switch on release immutability (Settings → Releases → "Enable release immutability").
It applies to future releases only. The first store release (`pinned-bytes-2026-09-27`) was published before it was
switched on, so its assets can still be deleted by an admin until they are republished into an immutable release.

## Bundles: restoring within the API quota (2026-09-28)

**Incident.** CI stopped at "Restore approved publisher bytes" with `HTTP 403: API rate limit exceeded for
installation`. It happened on the v4 freeze commit `0b667e2` (all four jobs), and again on `main` `fb1a9ab`: run
`36496536232`, both Python versions, and its re-run in the same quota window.

**Cause, from the logs and a request trace (`GH_DEBUG=api`):**
- For a private repository, `gh release download` makes one REST call to look up the release, then **one REST call per
  asset**; the redirect to storage is not an API call. The store's release holds 310 assets, so one restore spent about
  311 calls of the workflow token's hourly quota.
- Every push ran the CI workflow twice (push and pull_request) with two Python versions: four restores, and a fifth
  when `publisher-refresh` was triggered. That is about 1,250–1,560 calls per push, so a few pushes in an hour
  exhausted the quota.
- This was rate limiting, not a permissions problem ("Resource not accessible by integration") or a missing asset
  (which fails the SHA-256 check or reports "not found").

**Fix.** The approved bytes of every current pin are also published as **one bundle asset**, in a new release
(`pinned-bytes-bundle-2026-09-28`; the store stays add-only), and recorded under `bundles` in
`data/pinned_store.json`:
- **Bundle:** release, asset name, SHA-256 `547b3a1e…`, size 96,562,948 bytes, the 307 object keys, and a note.
- **Restore:** it downloads the bundle once (**two REST calls**), refuses it unless it hashes to the recorded value,
  and extracts only regular members named by a SHA-256 key the bundle lists. It then verifies **every object against
  its key and its current pin**, as before, and fails closed.
- **Unbundled objects:** anything outside a bundle (a later re-pin, a superseded object) comes from its own release as
  before.
- **Building it:** `scripts/publish_store_bundle.py` took every object from the store itself (not from a publisher),
  checked it against its key and pin, and built a deterministic archive (the same objects give the same SHA-256). It
  published the archive, downloaded it back to check all 307 objects, and only then recorded it.
- **Integrity:** `scripts/check_pin_changes.py` keeps bundle entries add-only, and `store-verify` checks their fields.
- **Error messages:** a failed download now names its cause: rate limited, permission denied, not found, transient
  (retried at most twice) or other.
- **Plain names only:** release tags and asset names read from the index must be plain names (letters, digits, `.`,
  `_`, `-`, starting with a letter or digit). `store-verify` checks them, and the backend checks them again before
  any `gh` call or path use. A name that fails is refused, and nothing is restored.
- **Every current pin must be in a bundle.** `store-verify`, and therefore CI, fails otherwise, so a new approved pin
  must include publishing and registering a new verified bundle (`docs/source-governance.md`, "Accepting a new
  version", step 5). A later bundle takes precedence for the objects it lists.
- **Recovery:** if a bundle asset is deleted or altered, every restore fails closed; nothing is substituted. Recover
  by publishing and registering a new bundle from the per-asset release, which remains the source. Enabling release
  immutability prevents edits to published assets.

**Verified (fresh home, no cache, 2026-09-28).**
- **Restore:** from 0 local files, `restore` put all 307 approved files in place in 4 s, with **1 `gh` invocation and
  2 REST API calls**. Each file was verified against its pin.
- **Build:** `build-data` reproduced `data_version` `8c14c217f5570d32` (0 failed sources). `build-index` reproduced
  `corpus_version` `221b6ea0f21e006d` (597 chunks, all 198 market notices).
- **Publishers:** `publisher-downloads --expect-none` reported none.

## Reuse terms (licensing assessment; not legal advice)

**AEMO** (all AEMO_PDF, NEMWeb, MMS Data Model and market-notice files):
- The terms page answers HTTP 403 to scripted clients. Its text was read from the Internet Archive capture of
  2026-09-23T18:07:05Z (<https://web.archive.org/web/20260923180705/https://www.aemo.com.au/privacy-and-legal-notices/copyright-permissions>;
  decoded HTML SHA-256 `5d09ba4e…817b`). It says:
  > "AEMO Material comprises documents, reports, sound and video recordings and any other material created by or on
  > behalf of AEMO and made publicly available by AEMO. … In addition to the uses permitted under copyright laws, AEMO
  > confirms its general permission for anyone to use AEMO Material for any purpose, but only with accurate and
  > appropriate attribution of the relevant AEMO Material and AEMO as its author. You do not need to obtain specific
  > permission to use AEMO Material in this way."
- Excluded: "confidential documents and any reports commissioned by another person or body who may own the copyright
  in them". None of the pinned files is either.
- The Demand Terms PDF itself says it "may be used in accordance with the copyright permissions on AEMO's website".
  The other PDFs carry no notice, but "a publication will be protected even if it does not display the © symbol", and
  the same general permission applies.
- **Assessment:** keeping verbatim copies in a private, access-controlled store, each with an attribution naming
  AEMO, the document or file, its URL and retrieval date, is a use "for any purpose" with attribution, so it is
  permitted. The permission would also allow wider sharing with attribution; this store stays private anyway.
- **Caveats:** read from an archived copy because the live page blocks scripts. Please confirm it in a browser.
  Decision D2 (no publisher files in git) is kept for size and separation, not for licensing.

**NASA POWER** (8 hourly API responses):
- <https://power.larc.nasa.gov/docs/referencing/>, fetched 2026-09-27T23:15:28Z (SHA-256 `97f49593…059b`), asks
  publications to include two acknowledgement texts: "The data was obtained from National Aeronautics and Space
  Administration (NASA) Langley Research Center's Prediction Of Worldwide Energy Resources (POWER) project funded
  through the NASA Earth Science Division." and "The data was obtained from the POWER Project's Hourly 2.x.x version on
  YYYY/MM/DD."
- It *requests* notification of publications and "if POWER data is transmitted to other researchers". It states no
  copyright restriction.
- **Assessment:** private storage is permitted and each object carries both acknowledgements. If collaborators are
  given access to the store, or results are published, send NASA the requested notification.

Not covered by this store: the embedding model (Hugging Face, pinned by revision and cached in CI) and Python packages
(pinned in `requirements.lock`, installed from PyPI).

## SO_OP_3705 Version 97 and the other superseded pins: recovered and verified

- **Where they were found:** GitHub still held the branch caches from the first CI runs (key
  `nem-raw-3a7ea10c…`, created 2026-09-23T09:01Z, before AEMO's 09:38Z replacement).
- **How they were recovered:** a one-off workflow on that branch (run 36357940231) restored the cache read-only and
  exported three files privately.
- **Verification here:**
  - SO_OP_3705: SHA-256 `481012861541…a3cd` equals the superseded pin; 1,267,581 bytes, 66 pages, "Version 97",
    effective 1 April 2026.
  - The two NASA responses match their superseded content hashes (`4ff47874…`, `b2bc691d…`; header sources GEOSIT).
- All three are `superseded` objects in release `pinned-bytes-2026-09-27`, with that provenance in the index.
- `data/pinned_store.json` lists no superseded pin as unavailable.

## Operations

```bash
make store-verify                       # index covers every current pin; every object fully described (no network)
make restore-pinned                     # restore approved bytes (needs read access to this repository via gh)
python scripts/publish_pinned_store.py --release pinned-bytes-<date> --target <commit> [--dry-run]
```

A machine without access to this private repository can still run `make data` / `make index` against the
publishers. Those downloads are verified against the pins. Market notices that have left NEMWeb, and any later
revisions, then show as unavailable or revised: see docs/source-governance.md.
