# M1 expected mappings: Glenn review required

All 20 cases are synthetic and pending review. These are reference answers for later milestones, not approved mappings. No eval metrics have been computed.

Read each input and expected mapping. Confirm source choices, transform parameters, missing fields and quarantine rows. Record acceptance by setting `review_status: approved` in its `case.yaml` only after reviewing it; edit the reference answer first when needed.

## Fixture contract

- Paths in `case.yaml` are relative to that file. Data rows are 1-based and exclude the CSV header.
- Every target field appears in `fields`, `unmapped_required`, or `unmapped_optional`. A missing required field is never invented.
- Each field uses one allowed transform. `rename` also means identity for an exact header. Rename of the source is implicit in every transform.
- `combine` joins sources in order using `separator`. `split` selects a zero-based `index` after splitting by the exact separator.
- `parse_date.format` uses Python strptime directives. `cast.type` is the target scalar type. `constant.value` requires an explicit source contract (case 19).
- `map_values.values` maps listed labels; unknown values remain unchanged and fail target validation if invalid. `drop` lists unused source columns.
- `expected_quarantine_rows` describes the future result after the expected mapping, including parse failures. M1 does not apply these transforms.
- `required_findings` is a small inspection regression oracle, not a mapping score. M1 is not expected to solve synonyms or split/combine decisions.
- No confidence is assigned to ground truth. Provider confidence and executable mapping validation belong to M2.

## Review checklist

| Review | Case | Schema | Expected quarantined rows |
|---|---|---|---|
| [x] | [01_customer_spec_example](cases/01_customer_spec_example/expected_mapping.yaml) | customer | 3 |
| [x] | [02_customer_header_typos](cases/02_customer_header_typos/expected_mapping.yaml) | customer | none |
| [x] | [03_customer_synonyms](cases/03_customer_synonyms/expected_mapping.yaml) | customer | none |
| [x] | [04_customer_combined_contact](cases/04_customer_combined_contact/expected_mapping.yaml) | customer | none |
| [x] | [05_customer_european_dates](cases/05_customer_european_dates/expected_mapping.yaml) | customer | 2 |
| [x] | [06_customer_enum_drift](cases/06_customer_enum_drift/expected_mapping.yaml) | customer | 3 |
| [x] | [07_customer_missing_email](cases/07_customer_missing_email/expected_mapping.yaml) | customer | 1, 2, 3 |
| [x] | [08_customer_extra_columns](cases/08_customer_extra_columns/expected_mapping.yaml) | customer | none |
| [x] | [09_order_header_renames](cases/09_order_header_renames/expected_mapping.yaml) | order | none |
| [x] | [10_order_numeric_casts](cases/10_order_numeric_casts/expected_mapping.yaml) | order | 2 |
| [x] | [11_order_status_drift](cases/11_order_status_drift/expected_mapping.yaml) | order | none |
| [x] | [12_order_slash_dates](cases/12_order_slash_dates/expected_mapping.yaml) | order | none |
| [x] | [13_order_missing_total](cases/13_order_missing_total/expected_mapping.yaml) | order | 1, 2, 3 |
| [x] | [14_order_header_typos](cases/14_order_header_typos/expected_mapping.yaml) | order | none |
| [x] | [15_ticket_synonyms](cases/15_ticket_synonyms/expected_mapping.yaml) | support_ticket | none |
| [x] | [16_ticket_combined_requester](cases/16_ticket_combined_requester/expected_mapping.yaml) | support_ticket | none |
| [x] | [17_ticket_split_subject](cases/17_ticket_split_subject/expected_mapping.yaml) | support_ticket | none |
| [x] | [18_ticket_nulls_and_formats](cases/18_ticket_nulls_and_formats/expected_mapping.yaml) | support_ticket | 2, 3 |
| [x] | [19_ticket_resolved_export](cases/19_ticket_resolved_export/expected_mapping.yaml) | support_ticket | none |
| [x] | [20_ticket_mixed_drift](cases/20_ticket_mixed_drift/expected_mapping.yaml) | support_ticket | 3 |

## 01_customer_spec_example

The SPEC example: renamed email, split name, subscription labels, US short dates; data row 3 has an invalid email.

[Input](cases/01_customer_spec_example/incoming.csv) · [Expected mapping](cases/01_customer_spec_example/expected_mapping.yaml) · [Review status](cases/01_customer_spec_example/case.yaml)

```yaml
fields:
  email:
    sources:
    - Email Address
    transform:
      name: rename
    reason: Email Address means email.
  full_name:
    sources:
    - First
    - Last
    transform:
      name: combine
      separator: ' '
    reason: Join given and family names in source order.
  plan:
    sources:
    - Subscription
    transform:
      name: map_values
      values:
        Pro Monthly: pro
        Free: free
    reason: The fixture uses these two subscription labels.
  signup_date:
    sources:
    - Joined
    transform:
      name: parse_date
      format: '%m/%d/%y'
    reason: This fixture explicitly uses month/day/two-digit year.
drop: []
unmapped_required: []
unmapped_optional: []
expected_quarantine_rows:
- 3
quarantine_reasons:
  3:
  - 'email: invalid email syntax'
```

## 02_customer_header_typos

Two transposed header letters; values are otherwise valid.

[Input](cases/02_customer_header_typos/incoming.csv) · [Expected mapping](cases/02_customer_header_typos/expected_mapping.yaml) · [Review status](cases/02_customer_header_typos/case.yaml)

```yaml
fields:
  plan:
    sources:
    - plan
    transform:
      name: rename
    reason: Use the source field unchanged.
  signup_date:
    sources:
    - signup_date
    transform:
      name: rename
    reason: Use the source field unchanged.
  email:
    sources:
    - emali
    transform:
      name: rename
    reason: Use the source field unchanged.
  full_name:
    sources:
    - full_nmae
    transform:
      name: rename
    reason: Use the source field unchanged.
drop: []
unmapped_required: []
unmapped_optional: []
expected_quarantine_rows: []
quarantine_reasons: {}
```

## 03_customer_synonyms

Semantic header synonyms. M1 need not infer these; the expected mapping is for the later provider evaluation.

[Input](cases/03_customer_synonyms/incoming.csv) · [Expected mapping](cases/03_customer_synonyms/expected_mapping.yaml) · [Review status](cases/03_customer_synonyms/case.yaml)

```yaml
fields:
  email:
    sources:
    - mailbox
    transform:
      name: rename
    reason: Use the source field unchanged.
  full_name:
    sources:
    - display_name
    transform:
      name: rename
    reason: Use the source field unchanged.
  plan:
    sources:
    - tier
    transform:
      name: rename
    reason: Use the source field unchanged.
  signup_date:
    sources:
    - registered
    transform:
      name: rename
    reason: Use the source field unchanged.
drop: []
unmapped_required: []
unmapped_optional: []
expected_quarantine_rows: []
quarantine_reasons: {}
```

## 04_customer_combined_contact

One Contact column contains name then email, separated by an exact space-pipe-space delimiter.

[Input](cases/04_customer_combined_contact/incoming.csv) · [Expected mapping](cases/04_customer_combined_contact/expected_mapping.yaml) · [Review status](cases/04_customer_combined_contact/case.yaml)

```yaml
fields:
  plan:
    sources:
    - plan
    transform:
      name: rename
    reason: Use the source field unchanged.
  signup_date:
    sources:
    - signup_date
    transform:
      name: rename
    reason: Use the source field unchanged.
  full_name:
    sources:
    - Contact
    transform:
      name: split
      separator: ' | '
      index: 0
    reason: Name is part zero.
  email:
    sources:
    - Contact
    transform:
      name: split
      separator: ' | '
      index: 1
    reason: Email is part one.
drop: []
unmapped_required: []
unmapped_optional: []
expected_quarantine_rows: []
quarantine_reasons: {}
```

## 05_customer_european_dates

Day/month/year dates; row 2 is an impossible calendar date and must remain invalid after parsing.

[Input](cases/05_customer_european_dates/incoming.csv) · [Expected mapping](cases/05_customer_european_dates/expected_mapping.yaml) · [Review status](cases/05_customer_european_dates/case.yaml)

```yaml
fields:
  email:
    sources:
    - email
    transform:
      name: rename
    reason: Use the source field unchanged.
  full_name:
    sources:
    - full_name
    transform:
      name: rename
    reason: Use the source field unchanged.
  plan:
    sources:
    - plan
    transform:
      name: rename
    reason: Use the source field unchanged.
  signup_date:
    sources:
    - signup_date
    transform:
      name: parse_date
      format: '%d/%m/%Y'
    reason: The fixture contract is day/month/year.
drop: []
unmapped_required: []
unmapped_optional: []
expected_quarantine_rows:
- 2
quarantine_reasons:
  2:
  - 'signup_date: impossible calendar date'
```

## 06_customer_enum_drift

Known plan labels can be mapped; Enterprise has no supported equivalent and must not be guessed.

[Input](cases/06_customer_enum_drift/incoming.csv) · [Expected mapping](cases/06_customer_enum_drift/expected_mapping.yaml) · [Review status](cases/06_customer_enum_drift/case.yaml)

```yaml
fields:
  email:
    sources:
    - email
    transform:
      name: rename
    reason: Use the source field unchanged.
  full_name:
    sources:
    - full_name
    transform:
      name: rename
    reason: Use the source field unchanged.
  plan:
    sources:
    - plan
    transform:
      name: map_values
      values:
        FREE: free
        Pro Monthly: pro
    reason: Map known labels only; preserve unknown labels for validation.
  signup_date:
    sources:
    - signup_date
    transform:
      name: rename
    reason: Use the source field unchanged.
drop: []
unmapped_required: []
unmapped_optional: []
expected_quarantine_rows:
- 3
quarantine_reasons:
  3:
  - 'plan: Enterprise is not in the target enum'
```

## 07_customer_missing_email

No email source exists. Leave email unmapped; never invent an address.

[Input](cases/07_customer_missing_email/incoming.csv) · [Expected mapping](cases/07_customer_missing_email/expected_mapping.yaml) · [Review status](cases/07_customer_missing_email/case.yaml)

```yaml
fields:
  full_name:
    sources:
    - full_name
    transform:
      name: rename
    reason: Use the source field unchanged.
  plan:
    sources:
    - plan
    transform:
      name: rename
    reason: Use the source field unchanged.
  signup_date:
    sources:
    - signup_date
    transform:
      name: rename
    reason: Use the source field unchanged.
drop: []
unmapped_required:
- email
unmapped_optional: []
expected_quarantine_rows:
- 1
- 2
- 3
quarantine_reasons:
  1:
  - 'email: required field has no source'
  2:
  - 'email: required field has no source'
  3:
  - 'email: required field has no source'
```

## 08_customer_extra_columns

Two extra columns are dropped. The phone sample must be masked during inspection.

[Input](cases/08_customer_extra_columns/incoming.csv) · [Expected mapping](cases/08_customer_extra_columns/expected_mapping.yaml) · [Review status](cases/08_customer_extra_columns/case.yaml)

```yaml
fields:
  email:
    sources:
    - email
    transform:
      name: rename
    reason: Use the source field unchanged.
  full_name:
    sources:
    - full_name
    transform:
      name: rename
    reason: Use the source field unchanged.
  plan:
    sources:
    - plan
    transform:
      name: rename
    reason: Use the source field unchanged.
  signup_date:
    sources:
    - signup_date
    transform:
      name: rename
    reason: Use the source field unchanged.
drop:
- sources:
  - phone_note
  transform:
    name: drop
  reason: Column is outside the target schema.
- sources:
  - internal_tag
  transform:
    name: drop
  reason: Column is outside the target schema.
unmapped_required: []
unmapped_optional: []
expected_quarantine_rows: []
quarantine_reasons: {}
```

## 09_order_header_renames

Capitalization and spaces differ from target names.

[Input](cases/09_order_header_renames/incoming.csv) · [Expected mapping](cases/09_order_header_renames/expected_mapping.yaml) · [Review status](cases/09_order_header_renames/case.yaml)

```yaml
fields:
  order_id:
    sources:
    - Order ID
    transform:
      name: rename
    reason: Use the source field unchanged.
  customer_email:
    sources:
    - Customer Email
    transform:
      name: rename
    reason: Use the source field unchanged.
  quantity:
    sources:
    - Quantity
    transform:
      name: rename
    reason: Use the source field unchanged.
  total:
    sources:
    - Total
    transform:
      name: rename
    reason: Use the source field unchanged.
  status:
    sources:
    - Status
    transform:
      name: rename
    reason: Use the source field unchanged.
  order_date:
    sources:
    - Order Date
    transform:
      name: rename
    reason: Use the source field unchanged.
drop: []
unmapped_required: []
unmapped_optional: []
expected_quarantine_rows: []
quarantine_reasons: {}
```

## 10_order_numeric_casts

JSON numeric strings require explicit output casts; many is not a valid integer. M1 accepts numeric text as an input representation.

[Input](cases/10_order_numeric_casts/incoming.json) · [Expected mapping](cases/10_order_numeric_casts/expected_mapping.yaml) · [Review status](cases/10_order_numeric_casts/case.yaml)

```yaml
fields:
  order_id:
    sources:
    - order_id
    transform:
      name: rename
    reason: Use the source field unchanged.
  customer_email:
    sources:
    - customer_email
    transform:
      name: rename
    reason: Use the source field unchanged.
  quantity:
    sources:
    - quantity
    transform:
      name: cast
      type: integer
    reason: Produce integers; a nonnumeric token fails.
  total:
    sources:
    - total
    transform:
      name: cast
      type: number
    reason: Produce numeric totals.
  status:
    sources:
    - status
    transform:
      name: rename
    reason: Use the source field unchanged.
  order_date:
    sources:
    - order_date
    transform:
      name: rename
    reason: Use the source field unchanged.
drop: []
unmapped_required: []
unmapped_optional: []
expected_quarantine_rows:
- 2
quarantine_reasons:
  2:
  - 'quantity: cannot cast many to integer'
```

## 11_order_status_drift

Three source status labels have explicit target equivalents in this synthetic export.

[Input](cases/11_order_status_drift/incoming.csv) · [Expected mapping](cases/11_order_status_drift/expected_mapping.yaml) · [Review status](cases/11_order_status_drift/case.yaml)

```yaml
fields:
  order_id:
    sources:
    - order_id
    transform:
      name: rename
    reason: Use the source field unchanged.
  customer_email:
    sources:
    - customer_email
    transform:
      name: rename
    reason: Use the source field unchanged.
  quantity:
    sources:
    - quantity
    transform:
      name: rename
    reason: Use the source field unchanged.
  total:
    sources:
    - total
    transform:
      name: rename
    reason: Use the source field unchanged.
  status:
    sources:
    - status
    transform:
      name: map_values
      values:
        Completed: paid
        Awaiting payment: pending
        Void: cancelled
    reason: 'Use the source contract: Completed means paid, Void means cancelled.'
  order_date:
    sources:
    - order_date
    transform:
      name: rename
    reason: Use the source field unchanged.
drop: []
unmapped_required: []
unmapped_optional: []
expected_quarantine_rows: []
quarantine_reasons: {}
```

## 12_order_slash_dates

Dates use year/month/day with slashes.

[Input](cases/12_order_slash_dates/incoming.csv) · [Expected mapping](cases/12_order_slash_dates/expected_mapping.yaml) · [Review status](cases/12_order_slash_dates/case.yaml)

```yaml
fields:
  order_id:
    sources:
    - order_id
    transform:
      name: rename
    reason: Use the source field unchanged.
  customer_email:
    sources:
    - customer_email
    transform:
      name: rename
    reason: Use the source field unchanged.
  quantity:
    sources:
    - quantity
    transform:
      name: rename
    reason: Use the source field unchanged.
  total:
    sources:
    - total
    transform:
      name: rename
    reason: Use the source field unchanged.
  status:
    sources:
    - status
    transform:
      name: rename
    reason: Use the source field unchanged.
  order_date:
    sources:
    - order_date
    transform:
      name: parse_date
      format: '%Y/%m/%d'
    reason: Read the stated year/month/day format.
drop: []
unmapped_required: []
unmapped_optional: []
expected_quarantine_rows: []
quarantine_reasons: {}
```

## 13_order_missing_total

Quantity alone cannot recover total; all rows lack a required amount.

[Input](cases/13_order_missing_total/incoming.json) · [Expected mapping](cases/13_order_missing_total/expected_mapping.yaml) · [Review status](cases/13_order_missing_total/case.yaml)

```yaml
fields:
  order_id:
    sources:
    - order_id
    transform:
      name: rename
    reason: Use the source field unchanged.
  customer_email:
    sources:
    - customer_email
    transform:
      name: rename
    reason: Use the source field unchanged.
  quantity:
    sources:
    - quantity
    transform:
      name: rename
    reason: Use the source field unchanged.
  status:
    sources:
    - status
    transform:
      name: rename
    reason: Use the source field unchanged.
  order_date:
    sources:
    - order_date
    transform:
      name: rename
    reason: Use the source field unchanged.
drop: []
unmapped_required:
- total
unmapped_optional: []
expected_quarantine_rows:
- 1
- 2
- 3
quarantine_reasons:
  1:
  - 'total: required field has no source'
  2:
  - 'total: required field has no source'
  3:
  - 'total: required field has no source'
```

## 14_order_header_typos

Typoed quantity and customer email headers.

[Input](cases/14_order_header_typos/incoming.csv) · [Expected mapping](cases/14_order_header_typos/expected_mapping.yaml) · [Review status](cases/14_order_header_typos/case.yaml)

```yaml
fields:
  order_id:
    sources:
    - order_id
    transform:
      name: rename
    reason: Use the source field unchanged.
  total:
    sources:
    - total
    transform:
      name: rename
    reason: Use the source field unchanged.
  status:
    sources:
    - status
    transform:
      name: rename
    reason: Use the source field unchanged.
  order_date:
    sources:
    - order_date
    transform:
      name: rename
    reason: Use the source field unchanged.
  quantity:
    sources:
    - quantitty
    transform:
      name: rename
    reason: Use the source field unchanged.
  customer_email:
    sources:
    - customer_emali
    transform:
      name: rename
    reason: Use the source field unchanged.
drop: []
unmapped_required: []
unmapped_optional: []
expected_quarantine_rows: []
quarantine_reasons: {}
```

## 15_ticket_synonyms

Support-system synonyms; values already follow the target enum and date conventions.

[Input](cases/15_ticket_synonyms/incoming.json) · [Expected mapping](cases/15_ticket_synonyms/expected_mapping.yaml) · [Review status](cases/15_ticket_synonyms/case.yaml)

```yaml
fields:
  phone:
    sources:
    - phone
    transform:
      name: rename
    reason: Use the source field unchanged.
  ticket_id:
    sources:
    - case_number
    transform:
      name: rename
    reason: Use the source field unchanged.
  requester_email:
    sources:
    - sender
    transform:
      name: rename
    reason: Use the source field unchanged.
  subject:
    sources:
    - title
    transform:
      name: rename
    reason: Use the source field unchanged.
  priority:
    sources:
    - severity
    transform:
      name: rename
    reason: Use the source field unchanged.
  status:
    sources:
    - state
    transform:
      name: rename
    reason: Use the source field unchanged.
  created_date:
    sources:
    - opened_on
    transform:
      name: rename
    reason: Use the source field unchanged.
drop: []
unmapped_required: []
unmapped_optional: []
expected_quarantine_rows: []
quarantine_reasons: {}
```

## 16_ticket_combined_requester

Requester contains display name then email, using a space-pipe-space delimiter.

[Input](cases/16_ticket_combined_requester/incoming.csv) · [Expected mapping](cases/16_ticket_combined_requester/expected_mapping.yaml) · [Review status](cases/16_ticket_combined_requester/case.yaml)

```yaml
fields:
  ticket_id:
    sources:
    - ticket_id
    transform:
      name: rename
    reason: Use the source field unchanged.
  subject:
    sources:
    - subject
    transform:
      name: rename
    reason: Use the source field unchanged.
  priority:
    sources:
    - priority
    transform:
      name: rename
    reason: Use the source field unchanged.
  status:
    sources:
    - status
    transform:
      name: rename
    reason: Use the source field unchanged.
  created_date:
    sources:
    - created_date
    transform:
      name: rename
    reason: Use the source field unchanged.
  phone:
    sources:
    - phone
    transform:
      name: rename
    reason: Use the source field unchanged.
  requester_email:
    sources:
    - requester
    transform:
      name: split
      separator: ' | '
      index: 1
    reason: Only part one is the email address.
drop: []
unmapped_required: []
unmapped_optional: []
expected_quarantine_rows: []
quarantine_reasons: {}
```

## 17_ticket_split_subject

Combine topic and detail into a single readable subject with colon-space.

[Input](cases/17_ticket_split_subject/incoming.csv) · [Expected mapping](cases/17_ticket_split_subject/expected_mapping.yaml) · [Review status](cases/17_ticket_split_subject/case.yaml)

```yaml
fields:
  ticket_id:
    sources:
    - ticket_id
    transform:
      name: rename
    reason: Use the source field unchanged.
  requester_email:
    sources:
    - requester_email
    transform:
      name: rename
    reason: Use the source field unchanged.
  priority:
    sources:
    - priority
    transform:
      name: rename
    reason: Use the source field unchanged.
  status:
    sources:
    - status
    transform:
      name: rename
    reason: Use the source field unchanged.
  created_date:
    sources:
    - created_date
    transform:
      name: rename
    reason: Use the source field unchanged.
  phone:
    sources:
    - phone
    transform:
      name: rename
    reason: Use the source field unchanged.
  subject:
    sources:
    - topic
    - detail
    transform:
      name: combine
      separator: ': '
    reason: Preserve both source parts in order.
drop: []
unmapped_required: []
unmapped_optional: []
expected_quarantine_rows: []
quarantine_reasons: {}
```

## 18_ticket_nulls_and_formats

Row 2 lacks a subject and has an invalid email. Row 3 has blank priority and an invalid phone.

[Input](cases/18_ticket_nulls_and_formats/incoming.json) · [Expected mapping](cases/18_ticket_nulls_and_formats/expected_mapping.yaml) · [Review status](cases/18_ticket_nulls_and_formats/case.yaml)

```yaml
fields:
  ticket_id:
    sources:
    - ticket_id
    transform:
      name: rename
    reason: Use the source field unchanged.
  requester_email:
    sources:
    - requester_email
    transform:
      name: rename
    reason: Use the source field unchanged.
  subject:
    sources:
    - subject
    transform:
      name: rename
    reason: Use the source field unchanged.
  priority:
    sources:
    - priority
    transform:
      name: rename
    reason: Use the source field unchanged.
  status:
    sources:
    - status
    transform:
      name: rename
    reason: Use the source field unchanged.
  created_date:
    sources:
    - created_date
    transform:
      name: rename
    reason: Use the source field unchanged.
  phone:
    sources:
    - phone
    transform:
      name: rename
    reason: Use the source field unchanged.
drop: []
unmapped_required: []
unmapped_optional: []
expected_quarantine_rows:
- 2
- 3
quarantine_reasons:
  2:
  - 'subject: required value is null'
  - 'requester_email: invalid syntax'
  3:
  - 'priority: blank required value'
  - 'phone: invalid international number'
```

## 19_ticket_resolved_export

Explicit fixture source contract: every ticket in this export is resolved, but the status column is omitted. Review the constant carefully. Drop internal columns.

[Input](cases/19_ticket_resolved_export/incoming.csv) · [Expected mapping](cases/19_ticket_resolved_export/expected_mapping.yaml) · [Review status](cases/19_ticket_resolved_export/case.yaml)

```yaml
fields:
  ticket_id:
    sources:
    - ticket_id
    transform:
      name: rename
    reason: Use the source field unchanged.
  requester_email:
    sources:
    - requester_email
    transform:
      name: rename
    reason: Use the source field unchanged.
  subject:
    sources:
    - subject
    transform:
      name: rename
    reason: Use the source field unchanged.
  priority:
    sources:
    - priority
    transform:
      name: rename
    reason: Use the source field unchanged.
  created_date:
    sources:
    - created_date
    transform:
      name: rename
    reason: Use the source field unchanged.
  phone:
    sources:
    - phone
    transform:
      name: rename
    reason: Use the source field unchanged.
  status:
    sources: []
    transform:
      name: constant
      value: resolved
    reason: The fixture explicitly declares this a resolved-only export; this is not
      inferred from missing data.
drop:
- sources:
  - internal_note
  transform:
    name: drop
  reason: Column is outside the target schema.
- sources:
  - agent_id
  transform:
    name: drop
  reason: Column is outside the target schema.
unmapped_required: []
unmapped_optional: []
expected_quarantine_rows: []
quarantine_reasons: {}
```

## 20_ticket_mixed_drift

Header normalization, priority codes, day-month-year dates and an extra column. P9 is unknown and must be quarantined.

[Input](cases/20_ticket_mixed_drift/incoming.json) · [Expected mapping](cases/20_ticket_mixed_drift/expected_mapping.yaml) · [Review status](cases/20_ticket_mixed_drift/case.yaml)

```yaml
fields:
  requester_email:
    sources:
    - requester_email
    transform:
      name: rename
    reason: Use the source field unchanged.
  subject:
    sources:
    - subject
    transform:
      name: rename
    reason: Use the source field unchanged.
  priority:
    sources:
    - priority
    transform:
      name: map_values
      values:
        P1: high
        P2: normal
    reason: P1 means high and P2 means normal; P9 has no known equivalent.
  status:
    sources:
    - status
    transform:
      name: rename
    reason: Use the source field unchanged.
  created_date:
    sources:
    - created_date
    transform:
      name: parse_date
      format: '%d-%m-%Y'
    reason: The export contract is day-month-year.
  phone:
    sources:
    - phone
    transform:
      name: rename
    reason: Use the source field unchanged.
  ticket_id:
    sources:
    - ticketid
    transform:
      name: rename
    reason: Use the source field unchanged.
drop:
- sources:
  - debug
  transform:
    name: drop
  reason: Column is outside the target schema.
unmapped_required: []
unmapped_optional: []
expected_quarantine_rows:
- 3
quarantine_reasons:
  3:
  - 'priority: unknown P9 code'
```
