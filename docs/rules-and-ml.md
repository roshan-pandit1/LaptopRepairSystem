# Explainable warnings, search, and future research

## Implemented rules

Rules evaluate the most recent received report, including partial availability; a previously available value is **not** substituted for a missing current one. Every finding has evidence IDs, source timestamps, trigger text, uncertainty, next check, and related case links.

| Signal | Trigger | Rationale / uncertainty |
|---|---|---|
| Free volume space | Below 10%; critical below 3%, configurable | Updates and temporary files need space. This is a capacity observation, not evidence of drive failure. |
| Battery deterioration | At least 3 distinct measurement days, non-increasing percent-of-design capacity, at least 8 percentage-point loss across the last 6 measurement days | Avoid manufacturing trends from retry snapshots. Same key/source/unit required. Firmware estimates, recalibration and replacement can alter readings. No exact failure date. |
| Storage health | Supported provider reports a status other than Healthy/OK/0 | Surface the provider observation; cannot identify the physical root cause. |
| Storage errors | Same key/provider cumulative read/write counter increases | Explicit difference with both readings; counters may reset or refer to changed hardware after replacement. |
| Relevant System events | At least 5 selected critical/error events in 7 days | Event IDs are investigated in context; a power-loss event can be a consequence, not a diagnosis. |

Configure thresholds through `GET /api/settings` and `PUT /api/settings` (`rules` object). Both boundaries validate limits and critical ≤ attention. No universal CPU temperature or SSD wear threshold is included. Trustworthy CPU package temperature is unavailable in the dependency-free collector; storage temperature is shown only if a supported reliability provider supplies it. A sustained thermal rule remains a future extension requiring a validated sensor mapping and manufacturer/model-specific thermal limits. No thermal prediction is currently claimed.

## Retrieval

FTS5 searches case fields and append-only events with sanitized token-prefix expressions. Structured filters are independent: category, brand, model, symptom, fault group, tests, suspected/confirmed causes, parts, review status, outcome, follow-up, and provenance class.

Similar-case scores are transparent ranking points, **not probabilities**:

- Symptom-token overlap: 2 points per shared term, capped at 10.
- Exact known manufacturer and model: 5 points.
- Same fault group: 4 points.
- At least two shared test terms: 2 points.
- Approved review and confirmed working at follow-up: 2 points.

Missing device fields do not count as exact matches. The UI lists match reasons and differences: model, missing structured numeric test data, and provenance/review class. Similarity suggests investigation paths; it never confirms a cause. Public aggregate and fictional case provenance stays visible.

## Optional AI boundary

AI is deliberately disabled in this MVP; the settings contract rejects `ai_enabled=true`. No key is necessary and no provider adapter is silently enabled. Deterministic warning explanations and similar-case rationales work offline.

A future opt-in provider adapter should receive a minimal read-only evidence bundle and return structured claims with `{case_id, event_id}` or measurement citations. Reject claims with missing citations; display unsupported suggestions as questions, not facts. Never expose collector tools to generated text. Treat notes, source pages and attachments as untrusted content and never use them as system instructions. Manufacturer recommendations require actual official source evidence. Keys belong in OS credential storage, never exported settings. Network disclosure requires a user-selected provider and explicit opt-in.

## Experimental predictive ML (not implemented)

Before modeling, define a failure endpoint and prediction horizon (for example, confirmed storage failure within 30 days); determine repair censoring and observation eligibility. Assemble longitudinal **pre-failure** measurements, confirmed failures, non-failure control periods, manufacturer/model context, and follow-up. Keep post-repair measurements and diagnostics that reveal the outcome out of pre-failure features.

Evaluate with:

1. Device-level separation across train/validation/test; never split scans of one device across folds.
2. Forward-in-time validation and a later held-out test period; freeze preprocessing on training data.
3. Precision and recall at operational alert thresholds with confidence intervals; stratify by manufacturer/model and provider availability.
4. Calibration curves and Brier score for a clearly specified horizon, only after genuine probability estimation is justified.
5. False alerts per device-month and alert burden per technician, lead time and missed-failure costs.
6. Drift, missingness, subgroup coverage, and a prospective silent evaluation before any user-visible risk score.

The current thresholds are never translated into numerical failure probabilities or exact failure dates.
