# registry-sync-window

## Purpose

Governs how `ktalk sync` bounds a single page request, continues across pages, restricts results
to a client-side date window (because the server does not honor date filters), protects the
registry against duplication the first time a domain switches to api-key mode, and exposes the
moment of the last completed sync to read-only consumers without requiring a mutating `sync` call
to observe it. Source: `content/30-requirements/personal-api-key.md` FR-14…FR-16; the last-sync
observability requirement — `content/30-requirements/registry-sync-observability.md` FR-41.

## Requirements

### Requirement: Page size never leaves the server's accepted range

Every list request issued during sync SHALL request between 1 and 100 items per page, regardless
of the caller's configured batch size — the server rejects `top`/`take` values above 100
(`ValidationError`). This SHALL hold for every paginated list surface sync touches (recordings,
participants, archive), not only the top-level recordings list.

#### Scenario: An oversized requested page size is clamped, not sent as-is

- **WHEN** a caller configures a page size larger than 100
- **THEN** every actual request SHALL carry a page-size parameter within `[1, 100]`

### Requirement: Pagination continues until an empty page, independent of a next-page field

The client SHALL continue fetching pages by advancing its own cursor (`skip` for the offset-based
surfaces, the server's `nextPageToken` where the surface provides one) until a page comes back
empty, rather than trusting a next-page-token field that a surface may not populate at all (the
plain recordings list never returns one). A window covering more than one page's worth of records
SHALL yield every record in the window, not only the first page.

#### Scenario: Pagination does not stop after the first page when no next-page field is present

- **WHEN** a list surface returns records without a next-page-token field
- **THEN** the client SHALL keep requesting subsequent pages by advancing `skip`, stopping only on
  an empty page

#### Scenario: A window spanning more than 100 records yields all of them

- **WHEN** a `--days N` window covers more than 100 records
- **THEN** the registry SHALL end up with every record in that window, not just the first 100

### Requirement: The sync date window is enforced by the client, not the server

The server SHALL NOT be trusted to honor `startFrom`/`startTo` — the client SHALL discard records
outside the requested `--days` window itself, after receiving each page, relying on the confirmed
descending sort order to stop fetching further pages once one page contains a record past the
window's threshold. A record whose date field is empty or unparsable SHALL be kept, not silently
dropped, because an unparsable date is not evidence the record is out of the window.

#### Scenario: Records past the window threshold are discarded by the client, not by server filtering

- **WHEN** the domain holds records outside the requested `--days` window
- **THEN** the client SHALL exclude them from the result regardless of what `startFrom`/`startTo`
  values were actually honored by the server

#### Scenario: A page containing a past-threshold record stops further page fetches

- **WHEN** a fetched page contains at least one record older than the window threshold
- **THEN** the client SHALL stop requesting further pages without additional network calls beyond
  that page

#### Scenario: A record without a parseable date is not dropped silently

- **WHEN** a record's date field is empty or fails to parse
- **THEN** the record SHALL be kept in the result, not discarded as if it were out of the window

### Requirement: A dry-run identifier reconciliation gates the first api-key sync

Before the first sync run in api-key mode is allowed to write to a registry that already holds
records synced in session mode, a dry run SHALL compare the set of record identifiers the api-key
response returns against only the portion of the existing registry that falls in the same date
window as the requested sync — not against the entire registry history, which would produce
near-universal false mismatches on a registry with a long history. A mismatch SHALL block the
ordinary (writing) sync from running automatically; a full match SHALL allow it to proceed.

#### Scenario: Dry run compares window to window, not window to the whole registry

- **WHEN** a dry run runs for a `--days N` window against a registry holding a much longer history
- **THEN** the comparison SHALL be scoped to registry records whose date falls within the same
  window as the dry run's `--days N`, not the full registry

#### Scenario: A mismatch blocks the ordinary sync

- **WHEN** the dry run finds identifiers present in the api-key response but absent from the
  window-scoped registry, or vice versa
- **THEN** the ordinary (writing) sync SHALL NOT proceed automatically — the mismatch SHALL be
  reported and require an operator decision

#### Scenario: A full match allows the ordinary sync to proceed

- **WHEN** the dry run finds the api-key response's identifiers and the window-scoped registry's
  identifiers to be identical sets
- **THEN** the ordinary sync MAY proceed

### Requirement: The last sync moment is exposed by a reading command, not only recorded internally

At least one documented reading command's `--json` output SHALL carry the moment of the most
recently completed sync, without requiring a mutating `sync` call to obtain it — the moment is
already recorded internally (the `meta` table) but SHALL also be reachable through a read path, so
a consumer can distinguish "nothing pending" from "stale, unsynced data" without triggering
`sync`'s own side effect of aging `new` records past the retention window into `skipped`. When no
sync has ever completed, the exposed value SHALL be an explicit absent-state marker, not a
silently omitted field. Reading the exposed value, any number of times, SHALL NOT change any
recording's status.

#### Scenario: A reading command surfaces the last completed sync moment

- **WHEN** a reading command's `--json` output is requested after at least one completed sync
- **THEN** the response SHALL carry the moment of that sync, matching the value the sync run
  recorded

#### Scenario: An unsynced registry states absence explicitly

- **WHEN** a reading command's `--json` output is requested before any sync has ever completed
- **THEN** the response SHALL mark the sync moment as explicitly absent, not omit the field
  silently

#### Scenario: Reading the sync moment never mutates registry data

- **WHEN** any reading command that exposes the sync moment is invoked, any number of times
- **THEN** no recording's status SHALL change as a side effect of that call
