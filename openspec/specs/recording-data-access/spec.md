# recording-data-access

## Purpose

Governs the four operations that read data beyond a recording's basic list/detail/transcript/
summary — downloading the video file, obtaining the full participant roster, listing the archive
of past conferences, and reading a meeting's chat messages — plus the observability contract for
detecting when the basic transcript read returns content belonging to a different recording than
the one requested. Source: `content/30-requirements/personal-api-key.md` FR-7…FR-10; the
transcript-identity observability requirement —
`content/30-requirements/transcript-identity-observability.md` NFR-17.

## Requirements

### Requirement: Video download streams to disk regardless of quality-name spelling

The client SHALL stream the recording file to the target path without buffering it whole in
memory. The quality name SHALL be normalized (case-insensitive, whitespace-insensitive) before
being matched or placed in a request URL, because the two data sources disagree on spelling
(`900p` without a space in session-mode data, `900 p` with a space in the api-key path template).
In session mode, a quality absent from the recording's available list SHALL be rejected with the
list of available qualities, not an unhandled exception. An existing target file SHALL NOT be
silently overwritten.

**Known limitation, scoped by design (not a defect):** in api-key mode, the recording-detail
response (`TalkDomainConferenceRecording`) carries no `qualities[]` field at all — there is no
list on this API surface to validate the requested quality against. The requested quality is
therefore used as-is and passed straight to the request URL; a wrong value surfaces as whatever
the raw network response returns, not as a curated `QualityNotFoundError`. This is an accepted
scope boundary for this wave, pending SA confirmation of whether a future API surface exposes an
api-key-mode quality list — it is not an oversight to silently work around.

#### Scenario: Quality-name spelling mismatch does not break the URL

- **WHEN** a download is requested with a quality name spelled with or without an internal space
  (`900p` vs `900 p`)
- **THEN** the client SHALL normalize it before building the request, and the request SHALL
  succeed structurally (no `InvalidURL` from an unescaped space)

#### Scenario: Requesting an unavailable quality names the available ones, in session mode

- **WHEN**, in session mode, the requested quality is not among the recording's available
  qualities
- **THEN** the client SHALL raise an error listing the qualities that are actually available,
  not an unhandled exception

#### Scenario: Api-key mode passes the requested quality through unvalidated

- **WHEN**, in api-key mode, a download is requested with any quality name
- **THEN** the client SHALL NOT attempt to validate it against a list (none is available on this
  API surface) — it SHALL send the request with that quality as given, not raise a curated
  "unavailable quality" error

#### Scenario: Download is streamed, not buffered whole

- **WHEN** a recording file of any size is downloaded
- **THEN** the client SHALL write it to disk incrementally as chunks arrive, not accumulate the
  full content in memory first

#### Scenario: An existing target file is not overwritten without an explicit flag

- **WHEN** the target path already exists and `overwrite` is not set
- **THEN** the client SHALL refuse before starting the network transfer, naming the existing path

### Requirement: Full participant roster merges sources without dropping anonymous participants

When the recording's own participant list is shorter than its reported participant count, the
client SHALL enrich it — through pagination in api-key mode, through a second, independent read
(the conference record) in session mode — rather than trusting the short list. Enrichment SHALL
trigger only when the count is strictly greater than the list length, not on every call. A
participant with `isAnonymous: true` and no `userInfo` SHALL be present in the merged result with a
distinguishable representation, never silently dropped. Merging two sources SHALL de-duplicate by
participant identity (the user's key/login, or the anonymous id), not by array position.

#### Scenario: Short participant list is enriched, not trusted as-is

- **WHEN** a recording's `participants[]` in the list response is shorter than its
  `participantsCount`
- **THEN** the client SHALL fetch the full roster rather than returning the short list as final

#### Scenario: Anonymous participants survive the merge

- **WHEN** a participant entry has `isAnonymous: true` and no `userInfo`
- **THEN** it SHALL appear in the result with a name derived from `anonymousName`, or a fallback
  label if that is also absent — never omitted

#### Scenario: Merging two overlapping sources does not duplicate participants

- **WHEN** the same participant appears in both the recording's own list and the conference
  record's list
- **THEN** the merged result SHALL contain that participant exactly once

### Requirement: Archive listing is api-key-only, paginated, and window-filterable

The archive of past conferences SHALL be reachable only in api-key mode; a request for it in
session mode SHALL be rejected with an explicit message naming api-key mode as the requirement,
not a bare `401`/`403` (the underlying path is confirmed unreachable under a session token). The
client SHALL exhaust pagination on the client side and return every matching conference in the
requested date window, not only the first page. A room-name filter, when supplied, SHALL be passed
through to the server.

#### Scenario: Archive is refused explicitly in session mode

- **WHEN** the archive is requested while session mode is active
- **THEN** the client SHALL refuse before any archive-specific network call, stating the archive
  is available only in api-key mode

#### Scenario: A date window spanning multiple pages returns every matching item

- **WHEN** api-key mode is active and the requested date window contains more items than fit on
  one page
- **THEN** the client SHALL continue fetching until the pagination is exhausted and return every
  item in the window, not only the first page

### Requirement: Chat messages resolve a channel before fetching, per-mode path

When no channel is given explicitly, the client SHALL determine one from the conference's own
metadata (its channels with messages) rather than sending a request the server is known to reject
with a raw `400` for a missing channel. The message-fetch path SHALL differ by auth mode (the
conference-history path in session mode, the api-key-only reporting path in api-key mode). A `403`
on a specific channel SHALL be reported as a permissions gap on that channel by name, not a bare
`403`.

#### Scenario: Missing channel is resolved automatically, not left to fail with a raw 400

- **WHEN** chat messages are requested without an explicit channel
- **THEN** the client SHALL first determine an available channel from the conference's metadata
  before requesting messages

#### Scenario: A channel without access is reported by name

- **WHEN** the server returns `403` for a specific chat channel
- **THEN** the message SHALL name that channel and state the caller lacks access to it, not
  surface a bare `403`

### Requirement: A transcript response's recording identity is independently verifiable, not assumed from a successful call

The client SHALL make available a way to determine, independently of the transcript response's own
success, whether transcript content returned for a requested `recording_id` actually corresponds
to that recording. The transcript-endpoint contract (`TalkTranscript`,
`talk.public.api-api-2.json`: `status`, `statusMessage`, `tracks`, `errors`, `transcriptId`,
`additionalProperties: false`) carries no field echoing the requested `recordingKey` or
`conferenceKey`, so a wrong-content response is otherwise indistinguishable from a correct one —
valid JSON, exit code 0, no error field. Verification SHALL be based on data independently
obtainable for the same `recording_id` (for example the recording's own participant roster), not
on any field of the transcript response itself, because no identity-echo field exists in the
contract.

**Known limitation, scoped by design (not a defect):** because the contract has no identity-echo
field, no mechanism can offer a deterministic, zero-cost confirmation — every verification path
costs at least one additional call to an independent source. Which independent source is used and
how the check is wired into `get-transcript` is an architecture decision, not fixed by this
requirement.

#### Scenario: An indistinguishable-by-default response is made distinguishable

- **WHEN** a transcript response is returned for a requested `recording_id`
- **THEN** the client SHALL make available an independent verification path that, when exercised,
  confirms or denies that the content belongs to the requested recording

#### Scenario: A correctly matched response does not trigger a false mismatch

- **WHEN** the independent verification path is exercised against a transcript response that
  genuinely belongs to the requested recording
- **THEN** it SHALL NOT report a mismatch

#### Scenario: An unavailable verification path is reported, not silently skipped

- **WHEN** the independent source needed for verification cannot be reached or fails
- **THEN** the client SHALL report that verification could not be performed, not treat the
  transcript response as confirmed

#### Scenario: A detected mismatch fails loudly, not silently

- **WHEN** identity verification reports a mismatch for a `get-transcript` response
- **THEN** the command SHALL exit with a status code distinct from success, from a usage error,
  and from a hard fetch failure, in addition to carrying the mismatch result in its output body

#### Scenario: An out-of-range chunk request does not silently drop the verification signal

- **WHEN** `get-transcript` is called with a chunk index outside the valid range for the
  requested transcript
- **THEN** identity verification SHALL NOT be attempted over the network for that call, and the
  response SHALL still carry an explicit signal that verification was not performed, naming the
  out-of-range chunk as the reason
