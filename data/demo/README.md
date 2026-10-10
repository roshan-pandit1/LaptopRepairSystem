# Fictional demo data

The deterministic fixture generator is `apps/api/demo.py`. The API seeds an empty workspace once with:

- Four measurement days (90, 60, 30 and 0 days ago) for a fictional ThinkPad T14 Gen 2.
- Battery capacity of 88 → 84 → 79 → 72 percent of design; constant 50,000 mWh design capacity.
- Low free storage (6.8%); CPU temperature explicitly unsupported.
- Six fictional repair case families and one linked repeat investigation.
- No invented official notices or publication dates.

UI-triggered **simulated** scans offer warning, no-warning, and unavailable-data scenarios. These use a deliberately delayed fixture generator, not claimed hardware tests. All reports carry `device.demo=true`, all measurements identify their fictional source, and the UI permanently marks the selected demo device.

Real devices have independent random identities and `demo=false`. Ingestion rejects attempts to change an existing identity's demo classification. Public aggregate records and fictional reviewed records have distinct provenance tags; neither is silently upgraded to a real verified repair.

Deleting the workspace sets an audit tombstone so the next startup does not silently recreate demo data. To obtain a completely fresh demo, start the API with a new `FAULTLINE_DATA_DIR` rather than deleting existing work.
