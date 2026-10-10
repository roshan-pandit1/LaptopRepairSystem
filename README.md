# FAULTLINE
### Laptop Health & Repair Intelligence

A local-first technician workbench that connects device observations, historical evidence, explainable warnings, and repair case histories. Built with React/TypeScript/Vite, Tailwind, FastAPI, SQLite, and a read-only Python collector for **macOS and Windows**.

## Run locally

Requirements: **Node.js 22+**, **Python 3.9+** (3.11/3.12 recommended), and npm. Commands below run from the project root, `/Users/roshanpandit/Desktop/LaptopRepair` on this machine.

### macOS / Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci
```

Terminal 1 — backend:

```bash
.venv/bin/python -m apps.api.main
```

Terminal 2 — frontend:

```bash
npm run dev
```

Open **http://127.0.0.1:5173**. Backend API documentation: **http://127.0.0.1:8000/docs**.

The first launch migrates SQLite and seeds a fictional demo. No external account, Windows agent or AI key is needed. Completed scans and repairs persist in `data/local/faultline.sqlite3` across restarts. Both services bind loopback; use the exact `127.0.0.1` frontend URL to match the origin policy.

### Real diagnostics on your Mac

In a third terminal, run the paired watcher:

```bash
.venv/bin/python -m apps.agent.collector --watch --token-file data/local/pairing-token --output data/local/macos-report.json
```

The workbench selects your connected Mac by default. Click **Run diagnostic scan → Request collector scan** for real readings. The Windows demo remains a separate, explicitly fictional device. The watcher does not enable scheduled monitoring by itself.

The macOS collector reads model/OS, CPU name and aggregate usage, installed memory and page-accounting snapshots, filesystem free space, supported SMART summary, and battery presence/capacity/cycles when exposed. Desktop Macs without a battery are explicitly identified. CPU temperature, detailed storage counters and unified system-error logs remain unavailable. See [macOS setup and limitations](docs/macos-diagnostics.md).

### Windows

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci
.venv\Scripts\python.exe -m apps.api.main
```

Run `npm run dev` in a second terminal. For a real paired collector, in a third terminal:

```powershell
.venv\Scripts\python.exe -m apps.agent.collector --watch --token-file data\local\pairing-token --output faultline-report.json
```

For Windows collection, the agent and API must run on the same Windows host. To inspect a separate Windows device from your Mac, generate a report on Windows and import the JSON through Settings instead:

```powershell
.venv\Scripts\python.exe -m apps.agent.collector --output faultline-report.json
```

The agent accepts `--categories battery storage cooling ram system`; omit unwanted categories. Standalone collection is an explicit user-triggered scan. The watcher respects API permissions and its own category allowlist. See [the complete Windows smoke test](docs/windows-smoke-test.md).

## Working MVP features

- Graphite/lime electronics workbench with keyboard-operable SVG component selection, evidence inspector, accessible historical charts/tables, responsive stacked mobile selector, and Ctrl/Cmd+K command palette.
- Clear demo/real-device labeling, selected-device inventory, collector connection status, scan selection, reported category progress, cancellation, partial reports, and persisted history.
- Value/unit/time/source/availability/limitation on every scan measurement. Zero is distinct from unknown, unsupported, permission denied and collection failure.
- Transparent battery-capacity trends, low free-space observations, supported storage health/counter warnings, and selected repeated system-event warnings. Every warning references its measurements and related cases.
- FTS5 case search, all requested structured filters, side-by-side comparison, explained similar-case ranking and differences.
- Append-only tests/bench measurements/notes, evidence attachments, suspected and evidence-supported confirmed diagnoses, parts/actions, post-tests, reviewer decisions, handover, follow-up, and linked repeat attempts. Failed tests return to investigation.
- Public aggregate records retain missing brand/model as null and are distinguished from technician investigations and fictional reviewed examples.
- Official-domain HTTPS source bookmarks tied to the selected exact model, with honest unknown publication/retrieval dates. No invented advisories or update availability.
- Activity log, saved diagnostic permissions, opt-in daily watcher monitoring, configurable rule thresholds in Settings and the API, local retention with confirmed cleanup, confirmed deletion, validated workspace export and report/workspace import.
- Private evidence storage and download endpoints; pairing-token-protected collector endpoints; local host/origin checks; bounded, fixed read-only OS commands.

## Windows checks and limitations

| Category | Supported data source | Important limitation |
|---|---|---|
| Manufacturer/model/OS | CIM `Win32_ComputerSystem`, `Win32_OperatingSystem` | Inventory may be unavailable if the provider fails; no hardware serial number is collected. |
| CPU | CIM `Win32_Processor` | Name/load snapshot only; no stress test. |
| Memory | CIM physical/visible/free memory | Capacity/usage, not a memory-integrity test. |
| Volumes | CIM `Win32_LogicalDisk` | Free space is not drive health. |
| Battery | `powercfg /batteryreport /xml` | Firmware estimates; absent packs or counters remain unavailable. |
| Storage | `Get-PhysicalDisk`, `Get-StorageReliabilityCounter` | Driver-dependent. Some counters need elevation; that is reported, not bypassed. |
| Events | Selected System log critical/error IDs from the past 7 days | Count capped at 1000 and detail metadata at 25; messages are omitted. Events do not prove a cause. |
| Temperature | Supported storage reliability temperature only | CPU package temperature is explicitly unsupported without a trustworthy optional provider. No universal thermal threshold is used. |

Normal collection never runs destructive disk checks, stress tests, repairs, registry modifications or firmware updates. No drivers or third-party sensor software are installed. Cancellation is cooperative between bounded categories; an in-flight OS command is not falsely reported as finished.

**Important scope:** real Windows commands are implemented and covered with mocked OS responses, but this macOS delivery environment cannot verify their behavior on a physical Windows laptop. Complete the documented smoke test before treating hardware compatibility as signed off. Software cannot discover every defect or predict an exact failure date.

Live manufacturer feeds, CPU temperature integration, model-specific sustained thermal rules, external AI providers, and predictive ML are **not implemented**. AI is visibly disabled and the core needs no API key. Advisories are manually added official-domain bookmarks, not fetched notices. Monitoring runs only while the watcher is running, not as an installed Windows service. This is a single-user local tool, not a multi-user authenticated service.

## Verification

```bash
.venv/bin/python -m pytest -q
npm run build
npx playwright install chromium
npm run test:e2e
npm audit
```

The backend tests use temporary independent databases. Playwright starts isolated servers on ports **8010 / 5174**, using `data/local/e2e`; it does not reuse or modify your live workspace on 8000 / 5173. The browser workflow covers component selection, simulated scan, reload/history, command palette, case search, complete repair/review/follow-up, and mobile layout. Screenshots are produced in `test-results/` (ignored).

Latest local verification: **29 Python tests passed**, **2 isolated Chromium end-to-end tests passed**, and **a real macOS browser-triggered diagnostic scan passed**. TypeScript/production build passed. The earlier npm dependency audit reported **0 vulnerabilities**; dependencies are unchanged. Desktop, mobile and real-Mac screenshots were inspected. Python transitive versions are pinned through `requirements.lock`; npm dependencies are locked in `package-lock.json`.

On Windows, change the Python executable in Playwright's `webServer.command` to `.venv\\Scripts\\python.exe`, retaining the uvicorn host/port arguments; the supplied auto-launch executable is POSIX. Python unit tests and the app itself run on either OS.

To explicitly verify a real Mac scan with the API, frontend and watcher running:

```bash
node scripts/smoke_macos.mjs
```

This initiates a real read-only scan, verifies device selection and demo isolation, and saves `data/local/macos-workbench.png`. Real Mac mini collection has been exercised here; physical MacBook battery validation and real Windows hardware validation remain separate checks.

Generate the versioned machine-readable contracts:

```bash
.venv/bin/python -m packages.schemas.export
```

Both raw agent reports and workspace archives use version `1.0`, with distinct envelopes. See [schema documentation](packages/schemas/README.md). Imports reject unsupported versions, invalid availability/value pairs, inconsistent timestamps and malformed workflow records at structural boundaries. Imported technician notes retain their supplied provenance; an import is not independent verification of a repair claim.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `FAULTLINE_DATA_DIR` | `<repo>/data/local` | SQLite, token and private evidence root; useful for fresh independent demos. |
| `FAULTLINE_FRONTEND` | `http://127.0.0.1:5173` | Exactly allowed browser origin. |
| `FAULTLINE_PAIRING_TOKEN` | Generated private token file | Optional token override for controlled environments/tests. Never commit it. |

The API logs the pairing-token **file location**, not its contents. Pair using `--token-file` to avoid secrets in command history. Rotate by stopping API/agent, removing only the token file, restarting API and reconnecting the agent. The file is owner-only on POSIX; on Windows protect the data folder with the current user's normal NTFS permissions.

Settings are available at `GET/PUT /api/settings`; rule thresholds are in `rules`. Saved retention does not silently erase repair history: **Apply retention cleanup** explicitly confirms deletion of old scans. Workspace export includes reports, case/event history, official-source metadata and settings. It intentionally excludes attachment bytes, pairing secrets, and audit logs; backup the private evidence directory separately if you need a full archival backup. Imported scheduling is always off.

## Privacy

No application telemetry, analytics, external font/CDN requests, personal document scanning, browser-history collection or password access. Device identity is a local random UUID rather than a serial number or hardware fingerprint. System event messages are excluded, and raw subprocess stderr is not logged/exported. User-entered notes and attachments may contain sensitive details; inspect them before sharing an export. Local storage is not encrypted at rest; use OS account access controls and disk encryption as appropriate.

## Troubleshooting

- **Disconnected UI / Failed to fetch:** start the API, then Vite; check `http://127.0.0.1:8000/api/health`. Use `127.0.0.1:5173`, not `localhost` or a network address. Vite refuses to silently select a different port.
- **Real scan disabled/disconnected:** run the watcher on the same Mac or Windows machine with the correct token; wait up to five seconds for the device selector. Offline reports can always be imported locally.
- **401:** token mismatch; verify the API and collector use the same data directory/token file. Never paste tokens into cases or screenshots.
- **Unsupported / permission denied:** expected on some firmware, drivers and Windows editions. Inspect the limitation. Other checks continue; unavailable is not healthy.
- **Case transition rejected:** add investigation tests before confirming a cause; use event IDs displayed in the timeline. Repair requires diagnosis, review requires passed post-tests, and handover requires reviewer approval. A failed repair needs new evidence.
- **Official URL rejected:** only the device manufacturer's allowlisted domain (or Microsoft) is accepted. Extend the documented domain map in `apps/api/main.py` after verifying another manufacturer's official domain. URLs are bookmarks, not fetched claims.
- **Empty after deletion:** intentional; deletion is not undone by automatic reseeding. For a fresh demo use a new `FAULTLINE_DATA_DIR`.
- **Large exports:** JSON request size is limited to 25 MB, attachment upload to 10 MB each. Export excludes binary evidence. No background retention deletion occurs.

## Design and technical notes

- [Architecture diagram, entities, trust boundaries and workflow](docs/architecture.md)
- [Rule rationale, retrieval ranking and future ML evaluation](docs/rules-and-ml.md)
- [Real Windows smoke-test procedure](docs/windows-smoke-test.md)
- [macOS diagnostics, setup and real-hardware smoke test](docs/macos-diagnostics.md)
- [Three-minute placement/demo script](docs/placement-demo.md)
- [Fictional dataset conventions](data/demo/README.md)

The central schematic is code-native SVG and intentionally illustrative, not a manufacturer-exact board drawing. Charts are data-driven; no generated imagery is used for schematics or measurements.
