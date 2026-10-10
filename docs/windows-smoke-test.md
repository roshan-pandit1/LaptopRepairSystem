# Real Windows smoke test

**Status:** automated tests use mocked Windows responses. This repository was built and tested on macOS; a real Windows hardware smoke test has not been executed here. The following procedure is the remaining hardware-validation gate.

## Supported environment

Windows 10/11 laptop, Python 3.9+ (3.11/3.12 recommended), built-in Windows PowerShell 5.1, and standard Windows CIM/Storage modules. Begin in a normal, non-administrator terminal. No third-party sensor driver is needed or installed.

From the repository root:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m apps.agent.collector --output faultline-report.json
```

1. Confirm collection finishes without elevation prompts. Check that the report has `schema_version: "1.0"`, `demo: false`, a random device ID, timezone-bearing timestamps, source and limitation for every reading.
2. Compare manufacturer/model, CPU and RAM against Windows System Information. The collector does not read serial numbers.
3. Compare volume free space against File Explorer. A zero value must remain available zero.
4. Generate a separate `powercfg /batteryreport` manually if desired. Compare design/full-charge capacity with the collector's percent-of-design; absent cycle count must be null/unknown. For a system without a battery, expect unsupported or an honest collection failure, not a healthy battery.
5. Inspect `Get-PhysicalDisk` / `Get-StorageReliabilityCounter` results manually. Unsupported or access-denied providers should affect only those readings. If a counter requires elevation, the application reports this; it never silently retries as administrator.
6. CPU temperature must be unsupported with the documented limitation. Supported storage temperature must identify the storage provider and must not be described as CPU temperature.
7. Verify selected event metadata has ID/provider/event time, not raw event messages or user paths. A zero-event result should be zero only when the query succeeded with no matches.
8. Inspect the output for absent serial numbers, computer names, usernames, browser history or personal files. Native battery XML is created only in a temporary directory and removed.

## Paired end-to-end scan

Start the API on the **same Windows host** in terminal 1:

```powershell
.venv\Scripts\python.exe -m apps.api.main
```

Start the frontend in terminal 2:

```powershell
npm ci
npm run dev
```

Start the agent in terminal 3:

```powershell
.venv\Scripts\python.exe -m apps.agent.collector --watch --token-file data\local\pairing-token --output faultline-report.json
```

Open `http://127.0.0.1:5173`. The device selector discovers the real device within five seconds. Select it, verify the real-device banner and connected status, choose categories, and start a scan. Progress must change only when categories actually finish. Cancel during collection and verify the terminal state and partial readings. An in-flight command can take up to 45 seconds before cancellation is acknowledged; storage comprises several independently bounded queries.

Stop/restart the API; scan history must survive. Stop the watcher; the device should become disconnected after its heartbeat expires. Requesting a real scan while disconnected must return an actionable message. Test a wrong token: ingestion must return HTTP 401.

## Offline transfer

If the API runs on macOS/Linux, copy `faultline-report.json` from Windows and use **Settings → Import JSON**. The collector does not connect across the network. A one-shot paired delivery on the same host is also available:

```powershell
.venv\Scripts\python.exe -m apps.agent.collector --send --token-file data\local\pairing-token
```

Record OS build, laptop model, Python version, provider availability, normal/elevated context, observed discrepancies and a scrubbed report when signing off this test. Do not substitute mocked results for this hardware check.
