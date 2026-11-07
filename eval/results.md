# Schema Fixer evaluation

Run: `m4-20261106`. Started UTC: 2026-11-06T15:28:33.646416+00:00.
Model: `gpt-6-luna`; reasoning: low; standard processing; zero retries. Dataset SHA256: `95d317e0baa66a71f69c7a7f29514001daf814412e02ffa24642cfaff790b913`.
Run code SHA256: `b829ebde5a83c659c749bbd7ef0c8b82e3a5e08186da127ff82cc09957f19398`. Report code SHA256: `c19cbc114410cc1bdead978a7033c57dd41f7f526e02e036ce8a026aa3b32c34`.

| Provider | Output match | Strict pass | Field accuracy | Missing recall | Confident wrong | Quarantine exact | API errors | Cost/file USD | Total USD | p50 seconds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 8/20 | 8/20 | 86/110 (78.2%) | 3/3 (100.0%) | 7/90 (7.8%) | 8/20 | 0 | $0.000000 | $0.000000 | 0.000018 |
| openai | 15/20 | 2/20 | 88/110 (80.0%) | 3/3 (100.0%) | 18/101 (17.8%) | 16/20 | 0 | $0.000262 | $0.005249 | 4.590984 |

## Scoring and measurement

- Output match (headline) is execution-based scoring, the same idea as execution accuracy in text-to-SQL benchmarks. A case matches when the draft passes local structure checks, every target yields the same validated values and row validity as the reference on every supplied row, and the predicted quarantine rows and fields are identical. It is measured on the supplied rows only: two transforms that agree here can still differ on unseen data. Example: `parse_date` with `%Y-%m-%d` accepts `2026-1-6`, which a plain rename rejects.
- Strict pass compares the transform itself. Field accuracy counts every schema target, including explicit missing declarations. Source order and transform parameters matter; entry order, confidence and explanation wording do not. Rename equals cast to the schema's own type. Other transformations, including redundant ISO parsers and identity value maps, count as strict mismatches; the failures table marks the ones with the same output.
- Missing recall uses reference missing fields. Confident wrong counts wrong target entries among emitted entries with confidence >= 0.8; abstentions have no confidence entry. Zero denominators are N/A.
- Case 19 uses the provider-stage answer: leave status unmapped. Its predicted invalid rows all lack status. The resolved constant in the fixture is a human-supplied post-approval contract, never provider input.
- Quarantine exact requires identical row positions AND failing target-field sets. Missing-required drafts are dry-validated for this prediction, including cases 07/13/19. Other structural failures are unevaluable and fail this metric. Nothing is approved or applied by evaluation.
- Strict pass requires target decisions, drop accounting, valid structure and quarantine predictions to match. Correct abstention can pass the eval while the CLI still blocks application until a human supplies missing required data.
- Latency is median wall time of provider calls, including failures, excluding profiling, scoring and disk writes. Baseline cost is zero. Provider errors are retained as failed decisions, not removed from denominators.
- Cost is an estimate using returned token usage and [2026-11-06 official pricing](https://developers.openai.com/api/docs/models/gpt-6-luna). Cached input and cache writes use separate rates; output tokens include reasoning. Missing accounting is unknown, not free. These are estimates, not invoice reconciliation.
- One run on 20 synthetic cases is not a production accuracy, reliability or speed guarantee. Only schema and masked profiles reach providers; case descriptions, reference answers and full rows do not.

## Failures

| Provider | Case | Field | Expected | Got | Reason |
|---|---|---|---|---|---|
| baseline | 01_customer_spec_example | full_name | {"sources": ["First", "Last"], "transform": {"name": "combine", "separator": " "}} | {"state": "unmapped_required"} | Source, transform, parameters or missing-field decision differs. |
| baseline | 01_customer_spec_example | plan | {"sources": ["Subscription"], "transform": {"name": "map_values", "values": [{"source": "Free", "target": "free"}, {"source": "Pro Monthly", "target": "pro"}]}} | {"state": "unmapped_optional"} | Source, transform, parameters or missing-field decision differs. |
| baseline | 01_customer_spec_example | signup_date | {"sources": ["Joined"], "transform": {"format": "%m/%d/%y", "name": "parse_date"}} | {"state": "unmapped_optional"} | Source, transform, parameters or missing-field decision differs. |
| baseline | 01_customer_spec_example | (drop) | [] | ["First", "Joined", "Last", "Subscription"] | Unused source accounting differs. |
| baseline | 01_customer_spec_example | (quarantine) | {"3": ["email"]} | {"1": ["full_name"], "2": ["full_name"], "3": ["email", "full_name"]} | Predicted row positions or failing target fields differ. |
| baseline | 02_customer_header_typos | email | {"sources": ["emali"], "transform": {"name": "rename"}} | {"state": "unmapped_required"} | Source, transform, parameters or missing-field decision differs. |
| baseline | 02_customer_header_typos | (drop) | [] | ["emali"] | Unused source accounting differs. |
| baseline | 02_customer_header_typos | (quarantine) | {} | {"1": ["email"], "2": ["email"], "3": ["email"]} | Predicted row positions or failing target fields differ. |
| baseline | 03_customer_synonyms | email | {"sources": ["mailbox"], "transform": {"name": "rename"}} | {"state": "unmapped_required"} | Source, transform, parameters or missing-field decision differs. |
| baseline | 03_customer_synonyms | full_name | {"sources": ["display_name"], "transform": {"name": "rename"}} | {"state": "unmapped_required"} | Source, transform, parameters or missing-field decision differs. |
| baseline | 03_customer_synonyms | plan | {"sources": ["tier"], "transform": {"name": "rename"}} | {"state": "unmapped_optional"} | Source, transform, parameters or missing-field decision differs. |
| baseline | 03_customer_synonyms | signup_date | {"sources": ["registered"], "transform": {"name": "rename"}} | {"state": "unmapped_optional"} | Source, transform, parameters or missing-field decision differs. |
| baseline | 03_customer_synonyms | (drop) | [] | ["display_name", "mailbox", "registered", "tier"] | Unused source accounting differs. |
| baseline | 03_customer_synonyms | (quarantine) | {} | {"1": ["email", "full_name"], "2": ["email", "full_name"], "3": ["email", "full_name"]} | Predicted row positions or failing target fields differ. |
| baseline | 04_customer_combined_contact | email | {"sources": ["Contact"], "transform": {"index": 1, "name": "split", "separator": " &#124; "}} | {"state": "unmapped_required"} | Source, transform, parameters or missing-field decision differs. |
| baseline | 04_customer_combined_contact | full_name | {"sources": ["Contact"], "transform": {"index": 0, "name": "split", "separator": " &#124; "}} | {"state": "unmapped_required"} | Source, transform, parameters or missing-field decision differs. |
| baseline | 04_customer_combined_contact | (drop) | [] | ["Contact"] | Unused source accounting differs. |
| baseline | 04_customer_combined_contact | (quarantine) | {} | {"1": ["email", "full_name"], "2": ["email", "full_name"], "3": ["email", "full_name"]} | Predicted row positions or failing target fields differ. |
| baseline | 05_customer_european_dates | signup_date | {"sources": ["signup_date"], "transform": {"format": "%d/%m/%Y", "name": "parse_date"}} | {"sources": ["signup_date"], "transform": {"name": "rename"}} | Source, transform, parameters or missing-field decision differs. |
| baseline | 05_customer_european_dates | (quarantine) | {"2": ["signup_date"]} | {"1": ["signup_date"], "2": ["signup_date"], "3": ["signup_date"]} | Predicted row positions or failing target fields differ. |
| baseline | 06_customer_enum_drift | plan | {"sources": ["plan"], "transform": {"name": "map_values", "values": [{"source": "FREE", "target": "free"}, {"source": "Pro Monthly", "target": "pro"}]}} | {"sources": ["plan"], "transform": {"name": "rename"}} | Source, transform, parameters or missing-field decision differs. |
| baseline | 06_customer_enum_drift | (quarantine) | {"3": ["plan"]} | {"1": ["plan"], "2": ["plan"], "3": ["plan"]} | Predicted row positions or failing target fields differ. |
| baseline | 11_order_status_drift | status | {"sources": ["status"], "transform": {"name": "map_values", "values": [{"source": "Awaiting payment", "target": "pending"}, {"source": "Completed", "target": "paid"}, {"source": "Void", "target": "cancelled"}]}} | {"sources": ["status"], "transform": {"name": "rename"}} | Source, transform, parameters or missing-field decision differs. |
| baseline | 11_order_status_drift | (quarantine) | {} | {"1": ["status"], "2": ["status"], "3": ["status"]} | Predicted row positions or failing target fields differ. |
| baseline | 12_order_slash_dates | order_date | {"sources": ["order_date"], "transform": {"format": "%Y/%m/%d", "name": "parse_date"}} | {"sources": ["order_date"], "transform": {"name": "rename"}} | Source, transform, parameters or missing-field decision differs. |
| baseline | 12_order_slash_dates | (quarantine) | {} | {"1": ["order_date"], "2": ["order_date"], "3": ["order_date"]} | Predicted row positions or failing target fields differ. |
| baseline | 15_ticket_synonyms | ticket_id | {"sources": ["case_number"], "transform": {"name": "rename"}} | {"state": "unmapped_required"} | Source, transform, parameters or missing-field decision differs. |
| baseline | 15_ticket_synonyms | requester_email | {"sources": ["sender"], "transform": {"name": "rename"}} | {"state": "unmapped_required"} | Source, transform, parameters or missing-field decision differs. |
| baseline | 15_ticket_synonyms | subject | {"sources": ["title"], "transform": {"name": "rename"}} | {"state": "unmapped_required"} | Source, transform, parameters or missing-field decision differs. |
| baseline | 15_ticket_synonyms | priority | {"sources": ["severity"], "transform": {"name": "rename"}} | {"state": "unmapped_required"} | Source, transform, parameters or missing-field decision differs. |
| baseline | 15_ticket_synonyms | status | {"sources": ["state"], "transform": {"name": "rename"}} | {"state": "unmapped_required"} | Source, transform, parameters or missing-field decision differs. |
| baseline | 15_ticket_synonyms | created_date | {"sources": ["opened_on"], "transform": {"name": "rename"}} | {"state": "unmapped_optional"} | Source, transform, parameters or missing-field decision differs. |
| baseline | 15_ticket_synonyms | (drop) | [] | ["case_number", "opened_on", "sender", "severity", "state", "title"] | Unused source accounting differs. |
| baseline | 15_ticket_synonyms | (quarantine) | {} | {"1": ["priority", "requester_email", "status", "subject", "ticket_id"], "2": ["priority", "requester_email", "status", "subject", "ticket_id"], "3": ["priority", "requester_email", "status", "subject", "ticket_id"]} | Predicted row positions or failing target fields differ. |
| baseline | 16_ticket_combined_requester | requester_email | {"sources": ["requester"], "transform": {"index": 1, "name": "split", "separator": " &#124; "}} | {"sources": ["requester"], "transform": {"name": "rename"}} | Source, transform, parameters or missing-field decision differs. |
| baseline | 16_ticket_combined_requester | (quarantine) | {} | {"1": ["requester_email"], "2": ["requester_email"], "3": ["requester_email"]} | Predicted row positions or failing target fields differ. |
| baseline | 17_ticket_split_subject | subject | {"sources": ["topic", "detail"], "transform": {"name": "combine", "separator": ": "}} | {"state": "unmapped_required"} | Source, transform, parameters or missing-field decision differs. |
| baseline | 17_ticket_split_subject | (drop) | [] | ["detail", "topic"] | Unused source accounting differs. |
| baseline | 17_ticket_split_subject | (quarantine) | {} | {"1": ["subject"], "2": ["subject"], "3": ["subject"]} | Predicted row positions or failing target fields differ. |
| baseline | 20_ticket_mixed_drift | priority | {"sources": ["priority"], "transform": {"name": "map_values", "values": [{"source": "P1", "target": "urgent"}, {"source": "P2", "target": "high"}]}} | {"sources": ["priority"], "transform": {"name": "rename"}} | Source, transform, parameters or missing-field decision differs. |
| baseline | 20_ticket_mixed_drift | created_date | {"sources": ["created_date"], "transform": {"format": "%d-%m-%Y", "name": "parse_date"}} | {"sources": ["created_date"], "transform": {"name": "rename"}} | Source, transform, parameters or missing-field decision differs. |
| baseline | 20_ticket_mixed_drift | (quarantine) | {"3": ["priority"]} | {"1": ["created_date", "priority"], "2": ["created_date", "priority"], "3": ["created_date", "priority"]} | Predicted row positions or failing target fields differ. |
| openai | 02_customer_header_typos | signup_date | {"sources": ["signup_date"], "transform": {"name": "rename"}} | {"sources": ["signup_date"], "transform": {"format": "%Y-%m-%d", "name": "parse_date"}} | Different transform with the same validated values and row validity on every fixture row. Counts toward output match; still a strict mismatch. |
| openai | 03_customer_synonyms | plan | {"sources": ["tier"], "transform": {"name": "rename"}} | {"sources": ["tier"], "transform": {"name": "map_values", "values": [{"source": "free", "target": "free"}, {"source": "pro", "target": "pro"}]}} | Different transform with the same validated values and row validity on every fixture row. Counts toward output match; still a strict mismatch. |
| openai | 03_customer_synonyms | signup_date | {"sources": ["registered"], "transform": {"name": "rename"}} | {"sources": ["registered"], "transform": {"format": "%Y-%m-%d", "name": "parse_date"}} | Different transform with the same validated values and row validity on every fixture row. Counts toward output match; still a strict mismatch. |
| openai | 04_customer_combined_contact | signup_date | {"sources": ["signup_date"], "transform": {"name": "rename"}} | {"sources": ["signup_date"], "transform": {"format": "%Y-%m-%d", "name": "parse_date"}} | Different transform with the same validated values and row validity on every fixture row. Counts toward output match; still a strict mismatch. |
| openai | 06_customer_enum_drift | plan | {"sources": ["plan"], "transform": {"name": "map_values", "values": [{"source": "FREE", "target": "free"}, {"source": "Pro Monthly", "target": "pro"}]}} | {"state": "unmapped_optional"} | Source, transform, parameters or missing-field decision differs. |
| openai | 06_customer_enum_drift | signup_date | {"sources": ["signup_date"], "transform": {"name": "rename"}} | {"sources": ["signup_date"], "transform": {"format": "%Y-%m-%d", "name": "parse_date"}} | Different transform with the same validated values and row validity on every fixture row. Counts toward output match; still a strict mismatch. |
| openai | 06_customer_enum_drift | (drop) | [] | ["plan"] | Unused source accounting differs. |
| openai | 06_customer_enum_drift | (quarantine) | {"3": ["plan"]} | {} | Predicted row positions or failing target fields differ. |
| openai | 07_customer_missing_email | signup_date | {"sources": ["signup_date"], "transform": {"name": "rename"}} | {"sources": ["signup_date"], "transform": {"format": "%Y-%m-%d", "name": "parse_date"}} | Different transform with the same validated values and row validity on every fixture row. Counts toward output match; still a strict mismatch. |
| openai | 08_customer_extra_columns | signup_date | {"sources": ["signup_date"], "transform": {"name": "rename"}} | {"sources": ["signup_date"], "transform": {"format": "%Y-%m-%d", "name": "parse_date"}} | Different transform with the same validated values and row validity on every fixture row. Counts toward output match; still a strict mismatch. |
| openai | 09_order_header_renames | order_date | {"sources": ["Order Date"], "transform": {"name": "rename"}} | {"sources": ["Order Date"], "transform": {"format": "%Y-%m-%d", "name": "parse_date"}} | Different transform with the same validated values and row validity on every fixture row. Counts toward output match; still a strict mismatch. |
| openai | 10_order_numeric_casts | quantity | {"sources": ["quantity"], "transform": {"name": "rename"}} | {"state": "unmapped_required"} | Source, transform, parameters or missing-field decision differs. |
| openai | 10_order_numeric_casts | order_date | {"sources": ["order_date"], "transform": {"name": "rename"}} | {"sources": ["order_date"], "transform": {"format": "%Y-%m-%d", "name": "parse_date"}} | Different transform with the same validated values and row validity on every fixture row. Counts toward output match; still a strict mismatch. |
| openai | 10_order_numeric_casts | (structure) | valid source/target accounting | ["unaccounted_source"] | Local mapping checks rejected the structure. |
| openai | 10_order_numeric_casts | (quarantine) | {"2": ["quantity"]} | not evaluable | Predicted row positions or failing target fields differ. |
| openai | 11_order_status_drift | order_date | {"sources": ["order_date"], "transform": {"name": "rename"}} | {"sources": ["order_date"], "transform": {"format": "%Y-%m-%d", "name": "parse_date"}} | Different transform with the same validated values and row validity on every fixture row. Counts toward output match; still a strict mismatch. |
| openai | 12_order_slash_dates | status | {"sources": ["status"], "transform": {"name": "rename"}} | {"sources": ["status"], "transform": {"name": "map_values", "values": [{"source": "cancelled", "target": "cancelled"}, {"source": "paid", "target": "paid"}, {"source": "pending", "target": "pending"}]}} | Different transform with the same validated values and row validity on every fixture row. Counts toward output match; still a strict mismatch. |
| openai | 13_order_missing_total | order_date | {"sources": ["order_date"], "transform": {"name": "rename"}} | {"sources": ["order_date"], "transform": {"format": "%Y-%m-%d", "name": "parse_date"}} | Different transform with the same validated values and row validity on every fixture row. Counts toward output match; still a strict mismatch. |
| openai | 13_order_missing_total | (drop) | [] | ["total"] | Unused source accounting differs. |
| openai | 13_order_missing_total | (structure) | valid source/target accounting | ["missing_drop_source"] | Local mapping checks rejected the structure. |
| openai | 13_order_missing_total | (quarantine) | {"1": ["total"], "2": ["total"], "3": ["total"]} | not evaluable | Predicted row positions or failing target fields differ. |
| openai | 14_order_header_typos | order_date | {"sources": ["order_date"], "transform": {"name": "rename"}} | {"sources": ["order_date"], "transform": {"format": "%Y-%m-%d", "name": "parse_date"}} | Different transform with the same validated values and row validity on every fixture row. Counts toward output match; still a strict mismatch. |
| openai | 15_ticket_synonyms | created_date | {"sources": ["opened_on"], "transform": {"name": "rename"}} | {"sources": ["opened_on"], "transform": {"format": "%Y-%m-%d", "name": "parse_date"}} | Different transform with the same validated values and row validity on every fixture row. Counts toward output match; still a strict mismatch. |
| openai | 16_ticket_combined_requester | created_date | {"sources": ["created_date"], "transform": {"name": "rename"}} | {"sources": ["created_date"], "transform": {"format": "%Y-%m-%d", "name": "parse_date"}} | Different transform with the same validated values and row validity on every fixture row. Counts toward output match; still a strict mismatch. |
| openai | 17_ticket_split_subject | created_date | {"sources": ["created_date"], "transform": {"name": "rename"}} | {"sources": ["created_date"], "transform": {"format": "%Y-%m-%d", "name": "parse_date"}} | Different transform with the same validated values and row validity on every fixture row. Counts toward output match; still a strict mismatch. |
| openai | 18_ticket_nulls_and_formats | created_date | {"sources": ["created_date"], "transform": {"name": "rename"}} | {"sources": ["created_date"], "transform": {"format": "%Y-%m-%d", "name": "parse_date"}} | Different transform with the same validated values and row validity on every fixture row. Counts toward output match; still a strict mismatch. |
| openai | 19_ticket_resolved_export | created_date | {"sources": ["created_date"], "transform": {"name": "rename"}} | {"sources": ["created_date"], "transform": {"format": "%Y-%m-%d", "name": "parse_date"}} | Different transform with the same validated values and row validity on every fixture row. Counts toward output match; still a strict mismatch. |
| openai | 19_ticket_resolved_export | phone | {"sources": ["phone"], "transform": {"name": "rename"}} | {"state": "unmapped_optional"} | Source, transform, parameters or missing-field decision differs. |
| openai | 19_ticket_resolved_export | (drop) | ["agent_id", "internal_note"] | ["agent_id", "internal_note", "phone"] | Unused source accounting differs. |
| openai | 20_ticket_mixed_drift | priority | {"sources": ["priority"], "transform": {"name": "map_values", "values": [{"source": "P1", "target": "urgent"}, {"source": "P2", "target": "high"}]}} | {"invalid_accounting": 0} | Source, transform, parameters or missing-field decision differs. |
| openai | 20_ticket_mixed_drift | (drop) | ["debug"] | ["debug", "priority"] | Unused source accounting differs. |
| openai | 20_ticket_mixed_drift | (structure) | valid source/target accounting | ["unaccounted_target"] | Local mapping checks rejected the structure. |
| openai | 20_ticket_mixed_drift | (quarantine) | {"3": ["priority"]} | not evaluable | Predicted row positions or failing target fields differ. |

## Per-case measurements

| Provider | Case | Output | Strict | Local checks | Latency seconds | Input tokens | Cached | Cache writes | Output tokens | Cost USD |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|
| baseline | 01_customer_spec_example | DIFF | FAIL | FLAGGED/no proposal | 0.000074 | N/A | N/A | N/A | N/A | $0.00000000 |
| baseline | 02_customer_header_typos | DIFF | FAIL | FLAGGED/no proposal | 0.000023 | N/A | N/A | N/A | N/A | $0.00000000 |
| baseline | 03_customer_synonyms | DIFF | FAIL | FLAGGED/no proposal | 0.000032 | N/A | N/A | N/A | N/A | $0.00000000 |
| baseline | 04_customer_combined_contact | DIFF | FAIL | FLAGGED/no proposal | 0.000014 | N/A | N/A | N/A | N/A | $0.00000000 |
| baseline | 05_customer_european_dates | DIFF | FAIL | FLAGGED/no proposal | 0.000010 | N/A | N/A | N/A | N/A | $0.00000000 |
| baseline | 06_customer_enum_drift | DIFF | FAIL | FLAGGED/no proposal | 0.000012 | N/A | N/A | N/A | N/A | $0.00000000 |
| baseline | 07_customer_missing_email | MATCH | PASS | FLAGGED/no proposal | 0.000009 | N/A | N/A | N/A | N/A | $0.00000000 |
| baseline | 08_customer_extra_columns | MATCH | PASS | PASSED | 0.000012 | N/A | N/A | N/A | N/A | $0.00000000 |
| baseline | 09_order_header_renames | MATCH | PASS | PASSED | 0.000079 | N/A | N/A | N/A | N/A | $0.00000000 |
| baseline | 10_order_numeric_casts | MATCH | PASS | PASSED | 0.000017 | N/A | N/A | N/A | N/A | $0.00000000 |
| baseline | 11_order_status_drift | DIFF | FAIL | FLAGGED/no proposal | 0.000015 | N/A | N/A | N/A | N/A | $0.00000000 |
| baseline | 12_order_slash_dates | DIFF | FAIL | FLAGGED/no proposal | 0.000014 | N/A | N/A | N/A | N/A | $0.00000000 |
| baseline | 13_order_missing_total | MATCH | PASS | FLAGGED/no proposal | 0.000013 | N/A | N/A | N/A | N/A | $0.00000000 |
| baseline | 14_order_header_typos | MATCH | PASS | PASSED | 0.000026 | N/A | N/A | N/A | N/A | $0.00000000 |
| baseline | 15_ticket_synonyms | DIFF | FAIL | FLAGGED/no proposal | 0.000060 | N/A | N/A | N/A | N/A | $0.00000000 |
| baseline | 16_ticket_combined_requester | DIFF | FAIL | FLAGGED/no proposal | 0.000018 | N/A | N/A | N/A | N/A | $0.00000000 |
| baseline | 17_ticket_split_subject | DIFF | FAIL | FLAGGED/no proposal | 0.000018 | N/A | N/A | N/A | N/A | $0.00000000 |
| baseline | 18_ticket_nulls_and_formats | MATCH | PASS | PASSED | 0.000014 | N/A | N/A | N/A | N/A | $0.00000000 |
| baseline | 19_ticket_resolved_export | MATCH | PASS | FLAGGED/no proposal | 0.000022 | N/A | N/A | N/A | N/A | $0.00000000 |
| baseline | 20_ticket_mixed_drift | DIFF | FAIL | FLAGGED/no proposal | 0.000021 | N/A | N/A | N/A | N/A | $0.00000000 |
| openai | 01_customer_spec_example | MATCH | PASS | PASSED | 6.971674 | 1553 | 0 | 1550 | 348 | $0.00036805 |
| openai | 02_customer_header_typos | MATCH | FAIL | PASSED | 3.376387 | 1524 | 1229 | 292 | 213 | $0.00015559 |
| openai | 03_customer_synonyms | MATCH | FAIL | PASSED | 3.927511 | 1521 | 1229 | 289 | 322 | $0.00020971 |
| openai | 04_customer_combined_contact | MATCH | FAIL | PASSED | 5.374777 | 1492 | 1229 | 260 | 347 | $0.00021859 |
| openai | 05_customer_european_dates | MATCH | PASS | PASSED | 4.839155 | 1521 | 1229 | 289 | 392 | $0.00024472 |
| openai | 06_customer_enum_drift | DIFF | FAIL | PASSED | 5.490084 | 1525 | 1229 | 293 | 282 | $0.00019022 |
| openai | 07_customer_missing_email | MATCH | FAIL | FLAGGED/no proposal | 4.379214 | 1483 | 1229 | 251 | 319 | $0.00020347 |
| openai | 08_customer_extra_columns | MATCH | FAIL | PASSED | 4.232452 | 1585 | 1229 | 353 | 370 | $0.00024172 |
| openai | 09_order_header_renames | MATCH | FAIL | PASSED | 4.369702 | 1660 | 1229 | 428 | 400 | $0.00026609 |
| openai | 10_order_numeric_casts | DIFF | FAIL | FLAGGED/no proposal | 4.255773 | 1660 | 1229 | 428 | 349 | $0.00024059 |
| openai | 11_order_status_drift | MATCH | FAIL | PASSED | 4.908826 | 1661 | 1229 | 429 | 483 | $0.00030772 |
| openai | 12_order_slash_dates | MATCH | FAIL | PASSED | 4.731463 | 1660 | 1229 | 428 | 437 | $0.00028459 |
| openai | 13_order_missing_total | DIFF | FAIL | FLAGGED/no proposal | 3.789436 | 1618 | 1229 | 386 | 276 | $0.00019884 |
| openai | 14_order_header_typos | MATCH | FAIL | PASSED | 3.567024 | 1662 | 1229 | 430 | 286 | $0.00020934 |
| openai | 15_ticket_synonyms | MATCH | FAIL | PASSED | 4.528151 | 1727 | 1229 | 495 | 452 | $0.00030046 |
| openai | 16_ticket_combined_requester | MATCH | FAIL | PASSED | 4.550354 | 1739 | 1229 | 507 | 483 | $0.00031747 |
| openai | 17_ticket_split_subject | MATCH | FAIL | PASSED | 4.812443 | 1765 | 1229 | 533 | 483 | $0.00032072 |
| openai | 18_ticket_nulls_and_formats | MATCH | FAIL | PASSED | 4.631615 | 1725 | 1229 | 493 | 459 | $0.00030371 |
| openai | 19_ticket_resolved_export | DIFF | FAIL | FLAGGED/no proposal | 6.138227 | 1765 | 1229 | 533 | 496 | $0.00032722 |
| openai | 20_ticket_mixed_drift | DIFF | FAIL | FLAGGED/no proposal | 5.264207 | 1763 | 1229 | 531 | 523 | $0.00034046 |
