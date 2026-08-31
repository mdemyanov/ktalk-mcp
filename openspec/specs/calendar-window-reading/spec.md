# calendar-window-reading

## Purpose

Governs reading scheduled meetings over a date window: transparent segmentation past the server's
7-day limit, the inclusive meaning of the window's right edge, honest signaling of a possibly
incomplete segment, and which query parameters the tool exposes to a caller. Source:
`content/30-requirements/rooms-calendar-scheduling.md` FR-18, FR-39.

## Requirements

### Requirement: A window wider than 7 days is segmented transparently

The server enforces a 7-day maximum only when both `start` and `end` are given explicitly. The
tool SHALL accept a window of any width from the caller and segment it into consecutive,
non-overlapping, at-most-7-day chunks itself — the caller SHALL NOT need to know about this
server-side limit, and SHALL NOT receive the server's raw `400` for exceeding it. Segmentation
SHALL cover every day of the requested window exactly once: no day skipped at a segment boundary,
no event duplicated across two segments.

#### Scenario: A window wider than 7 days returns every day without gaps or duplicates

- **WHEN** a window spanning more than 7 days is requested
- **THEN** the tool SHALL issue multiple segmented requests and return every meeting of every day
  in the window, with no meeting duplicated by identifier at the segment boundaries

#### Scenario: Missing start of window is rejected locally, not by the server's raw message

- **WHEN** the caller does not supply a start of the window at all
- **THEN** the tool SHALL reject the call itself with a message naming the missing start, not
  forward the server's raw `400` text

### Requirement: The window's right edge is inclusive of the named day

The server itself treats `end` as an exclusive boundary (`[start 00:00, end 00:00)`). This
capability's contract corrects for that at the tool boundary (ADR-017): a caller naming day `D` as
`--end D` SHALL see day `D`'s meetings in the result, the way a person reading "17 to 23 August"
expects the 23rd included. This is a deliberate behavior change, not backward-compatible with a
caller that already compensates for the server's exclusive boundary on its own side.

A single-day window (`--start D --end D`) SHALL return that day's meetings through both entry
points that reach this capability (CLI and the MCP tool) with identical results. A reversed window
(`start` later than `end`) SHALL be rejected before any network call, with a message distinct from
the server's raw text, and SHALL return a different exit code than a genuinely empty, honestly
computed day — the two outcomes SHALL NOT be indistinguishable to the caller.

#### Scenario: A single-day window returns that day's meetings

- **WHEN** `--start D --end D` is requested, for `D` at the start, middle, or end of a wider range
- **THEN** the result SHALL include every meeting scheduled on day `D`

#### Scenario: CLI and the MCP tool agree on the same single-day window

- **WHEN** the same single-day window is read through the CLI and through the
  `ktalk_list_calendar` MCP tool
- **THEN** both SHALL return the identical result — both surfaces reach the same underlying
  segmentation

#### Scenario: A reversed window is rejected before the network, with its own message and exit code

- **WHEN** `start` is later than `end`
- **THEN** the tool SHALL reject the call before any network request, with a message stating the
  start is later than the end (not the server's raw text about `end` needing to exceed `start`),
  and SHALL exit with a code distinct from the exit code of a genuinely empty result

#### Scenario: An honest empty day and a rejected window never share an exit code

- **WHEN** a window's actual, correctly computed result contains zero meetings
- **THEN** the exit code SHALL be the same "success, empty" code as any other successful read —
  and this code SHALL never also be produced by a rejected (invalid) window, so a caller cannot
  confuse "no meetings" with "the window was miscalculated or rejected"

### Requirement: A full segment page signals possible incompleteness; unexposed parameters stay unexposed

A segment response at the documented factual cap (100 elements) SHALL carry an explicit warning
that the segment may be incomplete — the server provides no working mechanism to fetch a
remainder for an over-full segment (`skip` is accepted but does not work here). A room-name filter,
when supplied, SHALL be passed to the server as-is. The `query` parameter SHALL NOT be exposed to
the caller at all, because the server accepts it syntactically without applying it as a filter —
exposing a non-functioning parameter would mislead the caller. Any description of the calendar read
SHALL avoid claiming or implying "your personal calendar" — the breadth of the returned data has
not been confirmed to be scoped to the caller specifically.

#### Scenario: A segment at the 100-item cap warns of possible incompleteness

- **WHEN** a fetched segment returns exactly 100 elements (the observed factual cap)
- **THEN** the caller SHALL receive an explicit warning that this segment may be incomplete,
  distinct from a segment that legitimately contains fewer than 100 items

#### Scenario: A room-name filter is forwarded; `query` is never exposed

- **WHEN** a room-name filter is supplied
- **THEN** it SHALL be forwarded to the server as given

- **WHEN** the tool's public parameter surface is inspected
- **THEN** it SHALL NOT include a `query` parameter for calendar reading

#### Scenario: Tool text never claims personal ownership of the calendar

- **WHEN** the tool's description or a message about the calendar read is inspected
- **THEN** it SHALL describe the result as "scheduled meetings visible to the active
  authorization", not as "your calendar" or an equivalent personal-ownership claim
