# Version 1.0 contracts

`report.py` is the authoritative strict Pydantic contract shared by backend and collector. Generated `agent-report-v1.schema.json` and `workspace-v1.schema.json` are portable JSON Schema artifacts. Regenerate with `python -m packages.schemas.export` when changing models.

## Agent report envelope

```json
{
  "schema_version": "1.0",
  "id": "report-unique-random-id",
  "device": {
    "id": "device-local-random-uuid",
    "manufacturer": "Example manufacturer",
    "model": "Exact model from CIM",
    "os": "Windows version from CIM",
    "demo": false
  },
  "started_at": "2026-01-01T10:00:00Z",
  "completed_at": "2026-01-01T10:00:02Z",
  "status": "completed",
  "categories": ["cooling"],
  "measurements": [{
    "key": "cpu_temperature",
    "component": "cooling",
    "value": null,
    "unit": "°C",
    "timestamp": "2026-01-01T10:00:01Z",
    "source": "No trustworthy CPU package sensor provider configured",
    "status": "unsupported",
    "limitation": "ACPI thermal zones are not assumed to identify CPU package temperature."
  }]
}
```

This is a **schema example**, not a real collected reading. Required availability states:

- `available`: a numeric or textual value is present; zero is valid.
- `unknown`: provider exists but no meaningful value is reported.
- `unsupported`: capability/provider not supported.
- `permission_denied`: access was denied; no implicit elevation.
- `collection_failed`: query, timeout, parsing or provider failure.

Every non-available value must be null. Units are explicit or null for categorical data. Timestamps require timezone, fit within report bounds, and cannot be materially in the future. Completed reports must represent every selected category, even with an unavailable measurement. Cancelled/failed reports may include only completed categories. Additional unknown fields are rejected. Device IDs and report IDs are bounded safe identifiers; category names are an enum, never executable instructions.

Pairing endpoints use `Authorization: Bearer <pairing-token>`:

- `POST /api/agent/poll`: register inventory and retrieve a category-only job.
- `POST /api/agent/scans/{id}/progress`: completed category names; returns cancellation request.
- `POST /api/agent/reports`: strict report ingestion.

The local UI can import a report with `POST /api/import`; browser-origin and loopback restrictions still apply. Import is intentional file transfer, not proof that data was measured on this host. The UI always shows the supplied source and whether a device is demo or real/imported.

## Workspace envelope

`kind: "faultline-workspace"`, `schema_version: "1.0"`, `exported_at`, `reports`, typed `cases` with append-only `events`, `advisories`, `settings`, and an explicit `limitations` string. Imported event evidence IDs are remapped; linked case IDs remain stable. Imports skip existing IDs rather than overwriting previous histories. No attachment bytes or pairing tokens are included. Missing source fields in public aggregate records remain null. Scheduling never becomes enabled merely by import.
