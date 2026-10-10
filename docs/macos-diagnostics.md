# macOS read-only diagnostics

The shared collector now detects macOS automatically. The same validated v1 report,
pairing token, scan progress, cancellation, permissions, database, and warning rules
are used on both macOS and Windows. The collector never invokes Apple Diagnostics,
`sudo`, stress tests, disk repairs, driver installs, or firmware updates.

## Start on your Mac

From the repository root, start these in separate terminals:

```bash
.venv/bin/python -m apps.api.main
npm run dev
.venv/bin/python -m apps.agent.collector --watch --token-file data/local/pairing-token --output data/local/macos-report.json
```

Open **http://127.0.0.1:5173**. The app automatically selects the connected real Mac;
it falls back to a saved real device before selecting a fictional demo. You can
explicitly select the Windows demo, and polling will respect that choice until
the page is reloaded. A prominent disclosure identifies simulated readings.

Click **Run diagnostic scan → Request collector scan**. Only selected, permitted
categories are collected. The watcher checks for requests every three seconds.
Progress comes from completed categories; cancellation is cooperative between
bounded OS commands. No repeated monitoring is enabled by starting the watcher.

For a one-shot real scan and authenticated upload:

```bash
.venv/bin/python -m apps.agent.collector --send --token-file data/local/pairing-token --output data/local/macos-report.json
```

Omit `--send` and `--token-file` to create a report without a running API. Import it
through Settings later. Use `--categories battery storage cooling ram system` to
specify categories; omit unwanted names. macOS identity is a random ID stored in
`data/local/agent/macos-device-id`, not a hardware serial number.

## Measurements and limitations

| Measurement | Read-only source | Interpretation |
|---|---|---|
| Mac family/model | `system_profiler SPHardwareDataType -json` | Only model-family/model-identifier fields retained. Serial/UUID omitted. |
| OS version and build | `sw_vers` | Installed version only; not an update-availability check. |
| CPU name and logical count | `sysctl` | Apple Silicon and Intel provider inventory. |
| CPU usage | `top -l 2 -s 1 -n 0` | Second aggregate sample, about one second; process details are not requested. |
| Installed RAM | `sysctl hw.memsize` | GiB; no memory-integrity test. |
| Memory accounting | `vm_stat` | Active + wired + physical compressor pages. Not Activity Monitor's Memory Used metric; no invented percentage. |
| Free/capacity | Filesystem `statvfs` through `shutil.disk_usage` | Data volume when present; APFS shared/purgeable storage can differ from Finder. |
| Storage health summary | `diskutil info -plist /` | Supported SMART `Verified` mapped to provider summary `Healthy`. Does not exclude defects. |
| Battery presence, cycles, capacity, charging | `ioreg -a -r -c AppleSmartBattery` | Respects `BatteryInstalled=false` / `IsPresent=false`. Desktop dummy entries are not treated as batteries. |

Full-charge capacity percentage is calculated only from raw `AppleRawMaxCapacity`
and `DesignCapacity` in matching mAh units. `MaxCapacity` can be normalized to
0–100 on Apple Silicon and is **never** divided by a raw mAh design value. Missing
fields stay unknown. A Mac without a battery gets an explicit unsupported result,
not zero capacity, a battery warning, or a fabricated cycle count.

CPU temperature, detailed NVMe wear/media-error counters, and unified system-error
logs are explicitly unavailable. There is no safe universal temperature interface
used by this implementation; unified log messages may contain sensitive details.
The Windows event rule is not applied to a fabricated zero macOS event count.

All subprocesses use fixed argument lists, `shell=False`, and a 30-second timeout.
Failure of one source does not suppress other results. Provider stderr is not
stored in reports. Hardware/profile output is reduced to allowlisted measurements;
identifiers, personal file contents, application names, and usernames are not retained.

## Verification

```bash
.venv/bin/python -m pytest -q
npm run build
npm run test:e2e
```

With all three local services running, explicitly exercise a **real scan** through
Chromium (this initiates a read-only hardware collection):

```bash
node scripts/smoke_macos.mjs
```

The live smoke test checks default real-Mac selection, local-agent status, real
scan completion, absence of fictional reading sources, unsupported CPU temperature,
component selection, demo isolation, and default selection after reload. Its
screenshot is saved to the ignored `data/local/macos-workbench.png`.

This development host reports itself as **Mac mini Mac18,5 / Apple M6 / 16 GiB /
macOS 27.0.1**. These are observed provider values, not hardcoded product metadata.
A real desktop smoke test validates this host's supported checks; MacBook battery
parsing is covered by mocks and still needs a physical MacBook smoke test.
