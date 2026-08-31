# talk-api-auth-modes

## Purpose

Governs how `ktalk-cli` resolves which credential authorizes a request to Контур.Толк, which
transport carries it, how the client diagnoses an expired credential versus a credential that
lacks a required scope, and how a caller checks the health of the active credential without
touching the local registry. Source: `content/30-requirements/personal-api-key.md` FR-1…FR-6,
FR-11; FR-19 of `content/30-requirements/rooms-calendar-scheduling.md` is merged here (SA
decision, ADR-021-spec §1) — `auth-status` diagnoses the same credential this capability
resolves, not a second contract.

## Requirements

### Requirement: Credential resolution order and mutually exclusive transport

The client SHALL resolve exactly one active credential from, in this order: an explicit personal
API key (`KTALK_PERSONAL_API_KEY`), a session token from the environment
(`KTALK_SESSION_TOKEN`), a session token previously written to the local token file
(`~/.config/ktalk-mcp/token` by default, `token_file.py`). If none of the three is present, the
client SHALL raise a configuration error naming both environment variables and the token-file
command, before any network call. A request SHALL carry either the `X-Auth-Token` header (personal
key) or the `sessionToken` query parameter (session token), never both, and never a query parameter
that is present but empty.

This order departs from `personal-api-key.md` NFR-2's two-source description (ключ → сессия →
явная ошибка): the token file is a third source added after that requirement was written
(`config.py::Settings._fall_back_to_token_file`), read only when both environment variables are
empty, so an explicitly set environment variable always overrides a stale file.

#### Scenario: Personal key takes priority over a session token

- **WHEN** both `KTALK_PERSONAL_API_KEY` and `KTALK_SESSION_TOKEN` are set
- **THEN** the client SHALL use the personal key exclusively — no request SHALL carry
  `sessionToken`, in query or elsewhere

#### Scenario: Session env var takes priority over the token file

- **WHEN** `KTALK_PERSONAL_API_KEY` is unset, `KTALK_SESSION_TOKEN` is set, and a token file exists
  on disk with a different value
- **THEN** the client SHALL use the environment variable's value, not the file's

#### Scenario: Token file is the fallback of last resort

- **WHEN** neither `KTALK_PERSONAL_API_KEY` nor `KTALK_SESSION_TOKEN` is set, and a token file
  exists
- **THEN** the client SHALL use the file's value as a session token, without requiring the caller
  to re-export an environment variable each session

#### Scenario: No credential anywhere is a configuration error, not a network error

- **WHEN** none of the three sources yields a value
- **THEN** the client SHALL fail before any network call, with a message naming
  `KTALK_PERSONAL_API_KEY`, `KTALK_SESSION_TOKEN`, and the token-file command as the three ways to
  resolve it

### Requirement: 401 and 403 are distinct diagnoses, worded per mode

A `401` response SHALL be reported as an expired-or-invalid credential, naming the variable to
refresh for the active mode (`KTALK_PERSONAL_API_KEY` in api-key mode, the session token in
session mode). A `403` response SHALL be reported as a permissions gap, not a credential problem,
and SHALL NOT suggest refreshing the credential. In api-key mode, a `403` tied to a known required
scope SHALL name that scope by its human-readable label, not only its raw string. An unparsable or
empty error body (observed for most `403` bodies) SHALL still produce a readable message, never a
raw traceback.

#### Scenario: 401 names the variable to refresh, per mode

- **WHEN** the API returns `401` in api-key mode
- **THEN** the message SHALL instruct the caller to refresh `KTALK_PERSONAL_API_KEY`

- **WHEN** the API returns `401` in session mode
- **THEN** the message SHALL instruct the caller to refresh the session token, not the personal key

#### Scenario: 403 never suggests refreshing a valid credential

- **WHEN** the API returns `403` while a required scope is known for the operation
- **THEN** the message SHALL name that scope and SHALL NOT suggest updating
  `KTALK_PERSONAL_API_KEY` or the session token

- **WHEN** the API returns `403` in session mode
- **THEN** the message SHALL state the session lacks permission for the operation and SHALL
  explicitly say the token itself is not the problem

#### Scenario: Unparsable error body still yields a readable message

- **WHEN** the response body is empty or not valid JSON (the common case for `403`)
- **THEN** the caller SHALL receive a readable message, not an unhandled parse error or a raw
  stack trace

### Requirement: Endpoint profile is keyed by operation and active mode; a missing profile fails before the network call

Every operation's path and required scope SHALL be looked up from a single table
(`OPERATION_PROFILES`) keyed by operation name and active auth mode, not branched inline per
method. An operation with no profile entry for the active mode SHALL be rejected before any
network request, with a message naming the operation and stating it is unavailable in the active
mode — never a bare `401`/`403` from a blind attempt.

#### Scenario: Session-only or api-key-only operation rejects the other mode before the network

- **WHEN** an operation's profile table has no entry for the currently active auth mode (for
  example the archive listing in session mode, or room/calendar/meeting-scheduling operations in
  api-key mode, at the time this capability is confirmed only for session mode)
- **THEN** the client SHALL reject the call before issuing any HTTP request, naming the operation
  and stating it is not available under the active mode

#### Scenario: List and detail operations resolve to different paths per mode

- **WHEN** the active mode is session
- **THEN** list/detail-of-recording operations SHALL use the internal, undocumented paths
  (`/api/recordings`, `/api/recordings/{key}`)

- **WHEN** the active mode is api-key
- **THEN** the same operations SHALL use the documented `Domain` paths
  (`/api/Domain/recordings/v2`, `/api/Domain/recordings/{key}`), each carrying its required scope

### Requirement: Credential resolution and diagnosis do not require the local registry

Checking the health of the active credential (`ktalk auth-status`) SHALL perform the diagnosis and
print its result even when the registry database file is unreachable (missing path, unreadable
directory, a `--db` pointing nowhere). A failure that originates in the diagnosis itself (network,
`401`/`403`) SHALL remain reported as an authorization diagnosis, never re-labeled as a database
error. No other CLI command's registry requirement SHALL change as a result.

#### Scenario: auth-status succeeds with an unreachable registry path

- **WHEN** `ktalk auth-status` runs with a `--db` path that does not exist
- **THEN** the command SHALL still perform the authorization diagnosis and print its result,
  not fail with a database-open error

#### Scenario: A diagnosis failure is never mislabeled as a database failure

- **WHEN** the diagnosis itself fails (network error, `401`, `403`)
- **THEN** the reported error SHALL describe the authorization failure, not the registry

#### Scenario: Every other registry-dependent command is unaffected

- **WHEN** any command other than `auth-status` (`sync`, `list`, `dashboard`, `show`, `mark-*`,
  `export`, `migrate`, `set-vault-id`) is run
- **THEN** it SHALL still require a reachable registry file exactly as before this capability

### Requirement: Auth-status diagnosis degrades honestly per mode and scope

In api-key mode, the diagnosis SHALL report `scopes[]` and `expiredAt` from a live request when the
key has the scope to read its own access info; if the key lacks that scope, the diagnosis SHALL
still report the key as alive (a `403` on this specific endpoint means "valid key, missing this one
scope", not "dead key") with an explicit note, not a bare `403`. In session mode, where no
scope/expiry endpoint exists, the diagnosis SHALL perform a live, minimal probe request and report
only aliveness — it SHALL NOT fabricate a scope or expiry value, and SHALL NOT skip the network
call in the name of parity with api-key mode.

#### Scenario: Api-key diagnosis with sufficient scope

- **WHEN** api-key mode is active and the key carries `application.applications.read`
- **THEN** the diagnosis SHALL return `scopes[]` and `expiredAt` from a live request

#### Scenario: Api-key diagnosis without the diagnosis's own scope

- **WHEN** api-key mode is active and the key lacks `application.applications.read`
- **THEN** the diagnosis SHALL report the key as alive, with a note that scope information is
  unavailable — not a raw `403`

#### Scenario: Session diagnosis performs a live probe, not a local guess

- **WHEN** session mode is active and the diagnosis is invoked
- **THEN** the client SHALL issue a minimal live request (a one-item recordings list) and report
  aliveness from its outcome, and SHALL state explicitly that scope/expiry are not available in
  this mode

### Requirement: The personal key and session token never appear in output

Neither `KTALK_PERSONAL_API_KEY` nor `KTALK_SESSION_TOKEN` SHALL appear, in full, in an exception
message, a log line, or CLI stdout/stderr (including `--json` output), across a representative set
of failure paths — a client-raised auth error, a generic network exception, and both text and JSON
CLI error output.

#### Scenario: Secret absent from client-raised and generic exceptions

- **WHEN** a request fails with a `401`/`403` classified by this client, or with an unrelated
  network exception
- **THEN** neither credential value SHALL appear anywhere in the exception's string representation

#### Scenario: Secret absent from CLI stderr in both output modes

- **WHEN** a CLI command fails while a credential is set, in plain-text mode or with `--json`
- **THEN** the printed error SHALL NOT contain the credential value
