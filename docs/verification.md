# Verification ledger

Latest run on this macOS machine: **29 Python tests passed; 2 isolated Chromium browser workflows passed; a real macOS browser-triggered diagnostic scan passed; production build passed.** The earlier npm audit reported 0 vulnerabilities and dependencies are unchanged. The real Windows smoke test remains unexecuted.

The real macOS smoke test verified automatic selection of the connected Apple device, authenticated scan requests/progress/completion, persisted real sources, unsupported temperature, explicit desktop battery absence, component selection, intentional demo selection and real-device default after reload. The runtime-identified host is Mac mini Mac18,5 / Apple M6 / 16 GiB / macOS 27.0.1. Physical MacBook battery collection remains to be checked; mocked battery tests cover raw/normalized capacity distinctions and phantom desktop registry entries.

## Implemented phases

1. React workbench, code-native SVG, component inspector and complete demo-facing UI; TypeScript/production build checked.
2. SQLite migrations, durable reports, case search, append-only repairs and linked repeats; isolated API tests checked.
3. Read-only Windows collector, strict report contract and token-protected ingestion; mocked CIM/PowerShell/battery parsing tests checked.
4. Historical measurements and configurable explainable warning rules; evidence references, same-day deduplication and unavailable-current-data behavior checked.
5. Official source bookmarks, activity, permissions/retention/export/import; AI remains explicitly disabled.
6. Browser end-to-end workflow, desktop/mobile screenshots, production build, backend tests and delivery documentation.

## Hardware validation boundary

Real Windows collection has **not** been executed on this macOS host. Passing mocked collector tests does not prove all firmware/driver combinations work. `windows-smoke-test.md` is the separate hardware acceptance procedure. Live advisory retrieval, AI providers, and predictive ML are not represented as tested/implemented features.

## Automated coverage

- Strict report parsing: version, units, timezone/range, zero/null, category coverage, unsupported values, finite numeric values.
- Agent pairing: missing/wrong token, real/demo isolation, local origin/Host checks, progress validation and cancellation.
- Rules: multi-day deterioration, same-day anti-duplication, unavailable-current evidence, referenced measurement IDs.
- Repair transitions: invalid jumps, supporting test IDs, failed post-test back to investigation, new evidence after failure, review identity, handover/follow-up, preserved linked repeat attempt.
- Search: FTS terms, structured filters, newly created cases, explained similarity, public aggregate missing fields.
- Persistence/export/import: API restarts, duplicate ID handling, validated imports, deletion confirmation, retention, no automatic demo resurrection.
- Evidence uploads: private download bytes and attachment disposition.
- Advisories: source-domain rejection, exact device model, unknown dates rather than invented metadata.
- Collector mocks: real XML structure/namespaces, missing battery cycles, denied storage counters, zero usage/free space, unsupported CPU temperature, timeout/no-shell enforcement, partial cancellation and loopback URL validation.
- Browser: component selection, scan completion and reload/history, command palette, search, create/test/diagnose/repair/post-test/review/handover/follow-up, and mobile selector without horizontal overflow.

Browser screenshots are generated under `test-results/`. The UI was inspected from captured desktop and mobile screenshots. No externally hosted images, fonts or generated chart images are required.
