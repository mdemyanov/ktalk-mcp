# room-diagnostics

## Purpose

Governs reading a room's configuration by name: the field set returned, the fact (established
after `rooms-calendar-scheduling.md` FR-17 was written) that this read has a write side effect,
and fail-closed behavior for the mode this operation has not been confirmed under. Source:
`content/30-requirements/rooms-calendar-scheduling.md` FR-17, [ADR-006](../../../content/00-project/adr/ADR-006-get-room-side-effect.md).

## Requirements

### Requirement: Room read returns the documented field set

Reading a room by name, in session mode, SHALL return an object carrying at least the 18 fields
confirmed by live probing: `roomName`, `sessionHalls`, `stageConferenceId`, `moderators`,
`anonymousModerators`, `allowAnonymous`, `anonymousAccessExpirationDate`,
`anonymousAccessModifiedDate`, `audioPolicy`, `videoPolicy`, `screenSharePolicy`, `isModerator`,
`conferenceId`, `sipSettings`, `onlineUsers`, `simultaneousTranslation`, `chatChannelSettings`,
`maskingSettings`.

#### Scenario: Reading an existing room returns all 18 documented fields

- **WHEN** a room is read by name in session mode
- **THEN** the result SHALL carry all 18 documented fields, present even when their value is
  `null`, not omitted

### Requirement: The server does not signal "room not found" — reading an unseen name has a write side effect

`content/30-requirements/rooms-calendar-scheduling.md` FR-17's original acceptance criterion — that
a caller reading a nonexistent room name gets an explicit "not found" message — is **disproved by
measurement**, not implemented: the server returns `200` for any room name, including a
guaranteed-fresh random one, and never returns `404`. This capability's contract follows the
measured fact (ADR-006), not the original hypothesis: this operation SHALL be treated as a
read-with-a-write-side-effect, not a pure read. A room name not previously seen by the circuit
SHALL be persisted as a side effect of the first read. This operation SHALL NOT be used to probe
whether a name is free — the act of checking creates occupancy.

#### Scenario: An unseen room name is created, not reported as absent

- **WHEN** a room name that has never been read before is requested
- **THEN** the server SHALL respond `200` with a room object (not `404`), and that name SHALL
  subsequently exist as a persisted room — the caller SHALL NOT receive a "room not found" message,
  because the server has none to give

### Requirement: Api-key mode fails closed until room read is confirmed under it

Room read has no confirmed endpoint profile for api-key mode. A caller in api-key mode SHALL be
rejected before any network call, with a message stating the operation is unavailable or
unconfirmed in the active mode — the client SHALL NOT attempt the call blindly on the strength of
an unverified documented analogue.

#### Scenario: Api-key mode rejects room read before the network call

- **WHEN** room read is requested while api-key mode is active
- **THEN** the client SHALL refuse before issuing any HTTP request, using the same fail-closed
  mechanism that already governs any operation without a confirmed profile for the active mode
