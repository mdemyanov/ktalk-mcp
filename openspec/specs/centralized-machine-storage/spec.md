# centralized-machine-storage

## Purpose

Governs the machine-wide, owner-only storage location the registry and its machine data
(transcripts, quality-eval reports) resolve to when a host project declares no path of its own:
where it lives, the permissions it and its contents carry, that migrating into it is an explicit
and reversible step, that two independent processes can write it concurrently without corruption,
and that it never silently lands inside a cloud-synced folder. Source:
`content/30-requirements/ktalk-plugin.md` FR-22, FR-25, NFR-12, NFR-13, NFR-14, NFR-15, NFR-16.

## Requirements

### Requirement: The store root resolves to one machine-wide path, created owner-only

The store root SHALL resolve to `${XDG_DATA_HOME:-$HOME/.local/share}/ktalk` (an empty
`XDG_DATA_HOME` SHALL be treated as unset, not as the path `""`). Two different host projects
resolving the default SHALL address the same file, not create one copy per project. The directory
SHALL be created, and kept, at permissions that exclude everyone but the owner (`0700`), applied
unconditionally on every resolution — not only at first creation — so a directory left with
loosened permissions by an older version or a restore is corrected, not left as-is.

#### Scenario: Two projects on the same machine share the same store root

- **WHEN** two different host projects, neither declaring its own registry path, each resolve the
  store root
- **THEN** both SHALL resolve to the identical path, not to two separate per-project paths

#### Scenario: The store root's permissions are corrected even if it already existed

- **WHEN** the store root directory already exists with looser-than-`0700` permissions (from an
  older version, manual creation, or a restored backup)
- **THEN** resolving the root SHALL reset it to `0700`, not leave the existing permissions as they
  were found

### Requirement: Migrating an existing registry into the store is explicit and reversible

Installing or running the package for the first time SHALL NOT itself move an existing registry
file into the centralized store — migration SHALL happen only through its own explicit command.
That command SHALL copy the source, verify the copy against the source by a full dump comparison,
and only then rename the source to a dated backup name (never delete it outright) — a verification
mismatch SHALL abort with the source untouched and the partial target removed. A second migration
attempt against a target that already exists SHALL refuse rather than overwrite data another
project may have already added there.

#### Scenario: Running the package does not migrate anything by itself

- **WHEN** the package is installed or run over an existing pre-central registry, without the
  migration command being invoked
- **THEN** the registry file SHALL remain at its original path — no operation other than the
  migration command SHALL move it

#### Scenario: A verification mismatch aborts without touching the source

- **WHEN** the dump comparison between the copied target and the source does not match
- **THEN** migration SHALL abort, the source SHALL be untouched, and the partially written target
  SHALL be removed, not left as a corrupt half-copy

#### Scenario: A second migration does not overwrite an existing target

- **WHEN** migration is invoked again and the target file already exists
- **THEN** it SHALL refuse, rather than overwrite data that may have been added to the target by
  another project since the first migration

#### Scenario: A documented, verifiable rollback path exists

- **WHEN** an operator needs to revert a completed migration
- **THEN** a documented sequence of steps SHALL exist and be executable without losing registry
  entries added after the migration — the pre-migration file is preserved under a dated backup
  name specifically to make this possible

### Requirement: Two independent processes can write the shared registry concurrently without corruption

Two separate operating-system processes (not threads) writing to the shared registry file at the
same time SHALL both either succeed, or fail with a recognizable "busy" error distinguishable from
a generic traceback — neither outcome SHALL corrupt the database file or lose a previously
committed record. When both processes write to the very same registry row concurrently (for
example one process marking it `done` while another marks the same row `skipped`), the final state
SHALL deterministically reflect exactly one of the two operations, decided by transaction
completion order — never a mixed or corrupted value.

#### Scenario: Concurrent writes from two processes preserve integrity and prior data

- **WHEN** two processes run write operations against the shared registry file at the same time
- **THEN** an integrity check after both complete SHALL pass, and no record committed before the
  concurrent run SHALL be missing afterward

#### Scenario: A conflicting write to the same row resolves to exactly one of the two values

- **WHEN** two processes write different values to the same registry row at overlapping times
- **THEN** the row's final value SHALL be exactly one of the two attempted values, determined by
  which transaction committed second, not a mix of both

### Requirement: The store's default path avoids known cloud-sync directories, and warns when the user overrides into one

The resolved machine-default path SHALL NOT sit inside a directory recognized as a cloud-sync
folder (iCloud Drive, Dropbox, OneDrive, Google Drive, and similarly recognized services) —
SQLite's WAL mode depends on POSIX locks that such volumes do not reliably honor. Recognition is
segment-based (matching whole path components, so `MyDropboxBackup/` does not falsely match
`Dropbox`), a known limitation, not a guarantee. If a user explicitly configures a path that this
segment check recognizes as a cloud-sync directory, the tool SHALL warn about the risk rather than
silently proceeding or blocking the choice outright.

#### Scenario: The resolved machine default never lands inside a recognized sync directory

- **WHEN** the machine-default store root is checked against the known sync-directory markers
- **THEN** it SHALL NOT match any of them

#### Scenario: A user-chosen path inside a recognized sync directory produces a warning, not silence or a hard block

- **WHEN** a user explicitly configures a store path that the segment-based check recognizes as a
  cloud-sync directory
- **THEN** the tool SHALL print an explicit warning naming the risk and SHALL still allow the path
  to be used — the choice remains the user's

### Requirement: Store contents stay owner-only, and never carry authorization secrets

Files and directories created inside the centralized store SHALL be readable and writable only by
the owning user (`0700` for directories, `0600` for files) — no world or group access. The store
SHALL carry only ktalk's own data (the registry database, raw transcripts, quality-evaluation
reports); it SHALL NOT carry `KTALK_SESSION_TOKEN` or `KTALK_PERSONAL_API_KEY` in any file, and
host-project artefacts (meeting protocols, the `registry.md` markdown mirror, participant
profiles) SHALL NOT be migrated into it — `export` SHALL keep generating that markdown mirror in
the host project, not in the store.

#### Scenario: Created files and directories are owner-only

- **WHEN** the store creates a directory or a file (registry database, transcript, report) inside
  itself
- **THEN** its permissions SHALL be `0700` for a directory and `0600` for a file — no access for
  group or others

#### Scenario: No authorization secret ever appears inside the store

- **WHEN** the store's contents are inspected after a representative series of operations across
  multiple projects
- **THEN** no file SHALL contain the value of `KTALK_SESSION_TOKEN` or `KTALK_PERSONAL_API_KEY`

#### Scenario: The markdown registry mirror stays in the host project, not the store

- **WHEN** `ktalk export` regenerates the markdown mirror of the registry
- **THEN** the mirror SHALL be written into the host project, exactly as before this capability —
  not into the centralized store
