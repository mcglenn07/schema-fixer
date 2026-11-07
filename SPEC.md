# Schema Fixer: Spec

Last updated: 2026-11-07

## What it does
Takes an incoming CSV or JSON file and a target schema. Finds every mismatch, asks an LLM to propose a mapping, checks that proposal in code, and asks a human to approve it. Approved mappings are saved and reused with no LLM call.

## Example
Target schema `schemas/customer.yaml`:
- `email`: string, email format, required
- `full_name`: string, required
- `plan`: enum `free`, `pro`
- `signup_date`: date

Incoming file headers: `Email Address, First, Last, Subscription, Joined` (dates like `11/06/26`)

Expected report:
- `Email Address` -> `email` (rename)
- `First` + `Last` -> `full_name` (combine)
- `Subscription` -> `plan`, value "Pro Monthly" not allowed, propose map_values to `pro`
- `Joined` -> `signup_date`, parse_date `%m/%d/%y`
- Rows with invalid emails go to quarantine, the rest import

## Pipeline
1. **Profile:** read the file with pandas. Per column: name, inferred type, null %, 3 sample values. Mask emails and phone numbers in samples.
2. **Detect:** compare to the target schema. Report missing required fields, absent optional fields (informational, never a failure), extra columns, likely renames, type mismatches, enum value drift, format mismatches.
3. **Propose:** the LLM receives ONLY the target schema and the column profiles, never the full file. It returns a `Mapping` (Pydantic, structured outputs). Per target field: source column(s), one transform from the allowed list, confidence (0 to 1), reason.
4. **Check in code:** every source column exists, every transform is on the allowed list, and mapped sample rows are checked with Pydantic. Structural errors flag the proposal. Individual transform or row-validation failures are warnings identifying rows that would be quarantined, not failures of the whole mapping. Flag the proposal when every checked row fails on the same target field, since that suggests a wrong mapping or transform. No rows are applied during this check.
5. **Approve:** CLI shows target, sources, transform, confidence, reason and check result. User explicitly types `accept`, edits the runtime Mapping YAML in `$VISUAL`/`$EDITOR`, or cancels (the default). Every edit is rechecked and must pass before acceptance. Save to `mappings/<source>.yaml`, with a version, approved status, approval time, relative schema path, canonical schema hash and source column names. An integrity hash detects accidental edits to the saved approval; changes require reapproval. This is a local approval record, not a cryptographic identity/signature.
6. **Apply:** deterministic, no LLM. Valid rows go to the output file. Invalid rows go to `quarantine.csv` with a reason per row. Output values are written in the target schema's types: numeric text that validates for an `integer` or `number` field is written as a number (`"3"` becomes `3`, `"19.99"` becomes `19.99`), and dates are written as ISO `YYYY-MM-DD`. A mapping does not need a `cast` for this; `cast` stays available for real conversions. (Decided by Glenn 2026-11-06.)

Apply reloads the bound schema, verifies its hash and the exact source column names (column order may differ), then reruns the code checks over **every** row. Structural failures and the all-rows same-field guard refuse the run before outputs are written. Individual dirty rows go to quarantine. JSON clean output preserves native scalar types; CSV has no native types and serializes the validated values. Optional missing fields are null/empty. The clean file defaults to `outputs/<input-stem>/clean.<csv|json>`, matching the input format, and `quarantine.csv` is written beside it even when empty. Quarantine has `data_row`, `reason`, and `original_row` (a JSON object preserving source keys, including keys named data_row/reason). Original values appear only in the quarantine file, never validation messages or apply reports. Existing destinations are never overwritten; both files are staged before publication and cleaned up on ordinary write failures.

Allowed transforms (the LLM picks from this list and never writes code): `rename`, `combine`, `split`, `parse_date(format)`, `map_values(dict)`, `cast(type)`, `constant(value)`, `drop`.

## Providers
- **Baseline:** rapidfuzz header-name matching, no LLM.
- **OpenAI (default):** one small model with structured outputs.
- **Ollama (stretch):** local 7B instruct model behind the same interface. Selected with the `PROVIDER` env var.

## Eval
- `eval/cases/`: 20 broken files built from 3 target schemas (customers, orders, support tickets). Each case has `expected_mapping.yaml`.
- Breakage types to cover: renames, synonyms, split and combined fields, date formats, enum drift, missing required fields, extra columns, header typos.
- Glenn reviews every `expected_mapping.yaml` before results count.
- Metrics per provider: field mapping accuracy, missing-field detection recall, confident-but-wrong rate (confidence >= 0.8 and wrong), quarantine correctness, cost per file, p50 latency.
- Output: `eval/results.md` with one table comparing providers, plus a failures table (case, field, expected, got, reason).
- M4 scores every schema target decision (including explicitly unmapped fields). Field mapping accuracy is correct decisions / all target fields; missing-field recall is correct missing declarations / reference missing fields; confident-but-wrong is incorrect emitted target entries with confidence >= 0.8 / all emitted target entries at that confidence. Drop coverage and structural validity are also required for a case pass. Confidence and reason text are not answer-key equality criteria.
- Normalize reference dictionaries and runtime lists/pairs, ignoring entry/key ordering except source order. `rename` and `cast` to the schema's own type are equivalent. Case 19's provider-stage reference leaves required status unmapped, not guessed constant resolved; its predicted quarantine has all rows failing status. The checked-in fixture remains the post-approval answer and is never changed by the runner.
- Quarantine correctness means an exact match of 1-based row positions and failing target-field sets, not English reason strings. Eval-only dry validation predicts invalid rows even for missing-required-field drafts (cases 07, 13, 19); it never approves/applies them. Other structural defects make quarantine unevaluable and count as a failure. Case pass means correct provider decisions, drops and quarantine predictions, not permission to apply a draft.
- Every run requires all cases approved before any provider is called. The default runner is baseline-only. OpenAI selection is explicit, with one attempt per case, no retries, and a new run directory. A started record is written before a call; existing run directories cannot be rerun. Persist safe per-case mappings, usage, latency and scores plus a dataset/code/pricing manifest; report-only mode rebuilds results offline.
- p50 latency is the median provider call duration including failed attempts, excluding profiling/scoring/file I/O. Cost is a USD estimate from returned token usage and the dated pricing snapshot, including cache reads/writes and total output tokens (reasoning included). Missing usage/prices are unknown, not zero. Report total and per-file cost, denominators, request errors, all failures and one-run/synthetic-set limits.

## CLI
- `schema-fixer inspect data.csv --schema schemas/customer.yaml`: mismatch report
- `schema-fixer propose data.csv --schema ... --provider baseline|openai|ollama`: mapping draft
- `schema-fixer approve data.csv --schema ... --provider baseline|openai [--output mappings/source.yaml] [--sample-size 20]`: propose, review, edit and explicitly accept; default output is `mappings/<input-stem>.yaml`. Provider selection matches propose. Sample size is 1-100, default 20.
- `schema-fixer approve data.csv --schema ... --draft draft.yaml [--output mappings/source.yaml] [--sample-size 20]`: offline review of runtime Mapping YAML or JSON (also accepts the mapping from a propose JSON report or saved approval). Cannot combine --draft and --provider. Draft/edit checks and acceptance are identical; no provider is invoked.
- `schema-fixer apply data.csv --mapping mappings/x.yaml`: clean file + quarantine.csv
- `schema-fixer apply data.csv --mapping mappings/x.yaml [--output outputs/run/clean.csv|clean.json] [--json]`: select clean output location/format; quarantine.csv is its sibling. --json prints counts, file paths and safe checks only. No provider, sample-size option or approval bypass. Exit 0 means outputs written (possibly with quarantine), 1 means refused code checks, 2 means input/binding/output error. Approve exits 0 on save, 1 on cancellation or refused checks, 2 on input/provider/write error.
- `python eval/run_eval.py`: writes eval/results.md
- `python eval/run_eval.py [--providers baseline openai] [--run-dir eval/runs/<new-name>] [--output eval/results.md]`: baseline-only by default; selecting openai makes paid calls. Run with the project's Python environment (for example uv run python). --run-dir must be new; no retry/resume mode.
- `python eval/run_eval.py --report-only --run-dir eval/runs/<saved-run> [--output eval/results.md]`: rebuild results from saved attempts with no provider calls; verify dataset fingerprint first. Exit 0 means the evaluation/report completed (mapping failures remain in the report), 1 means provider errors/incomplete attempts, 2 means configuration/input/approval-gate errors.

## Engineering
uv, Python 3.12, pinned deps, Typer, Gradio (M5 only), pandas, Pydantic v2, rapidfuzz, openai SDK, ruff, pytest (LLM calls mocked, no network in tests), GitHub Actions running ruff and pytest. Config through env vars. `.env.example` lists names only.

## README
Problem, Mermaid diagram of the pipeline, results table, how to run, limits (synthetic test cases, small eval set).

## Milestones
- **M0:** continuity files (done 2026-11-06)
- **M1:** schemas, profiler, detector, 20 eval cases with expected mappings. No LLM yet. STOP: Glenn reviews the expected mappings.
- **M2:** baseline proposer, OpenAI proposer, code checks. STOP.
- **M3:** approve flow, apply, quarantine. STOP.
- **M4:** eval run, README, CI. STOP.
- **M5:** Gradio demo page (`app.py`). STOP. See Demo page below.
- **Stretch:** Ollama provider, added as a column in results.md.

## Demo page (M5)
- Run locally with `uv run python app.py`; bind to 127.0.0.1 without a public share link. app.py is a thin entry point to the package UI.
- Upload a CSV or JSON file and pick a target schema from a dropdown.
- Show the mismatch report, then the proposed mapping as a table with confidence and check results.
- Approve button applies the mapping. Download buttons for `clean.csv` and `quarantine.csv`.
- Provider dropdown defaults to `baseline`, so the demo works with no API key. `openai` only appears when `OPENAI_API_KEY` is set.
- Include 2 or 3 sample broken files the visitor can load with one click.
- The three built-in samples are synthetic customer, order and ticket files. Loading a sample selects its schema; inspection/proposal requires a separate click. Changing a file, schema or provider clears the draft and downloads. A flagged draft cannot be approved.
- Approval rechecks the reviewed input and schema, saves a schema-bound approval in that session's temporary directory, and calls the same full-file apply as the CLI. Downloads are CSV even for JSON input. Session files expire; durable approval editing/reuse stays in the CLI. Disable Gradio analytics and public sharing; hosting remains undecided.
- Calls the same package functions as the CLI. No new logic in `app.py`.
- Record a short GIF of the page for the README.
- Hosting: TBD (decide after M5 runs locally).

## Non-goals
No web UI beyond the M5 Gradio demo page. No database. No auto-apply without approval. No LLM-written code. No live API or webhook ingestion.
