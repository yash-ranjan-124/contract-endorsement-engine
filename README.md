# Contract Endorsement Engine

A Django REST API and React application for managing insurance contracts and their endorsements.

## Features

- Preserve original contract slips without modification.
- Record numbered endorsements for cover changes, premium adjustments, extensions, and cancellations.
- Calculate a contract’s as-amended position on a selected date.
- Apply agreed endorsements in number order; exclude drafts.
- Calculate premiums and cancellation refunds using exact decimal arithmetic.
- Import sample data with clear rejection reasons.
- Compare the original slip and amended position in the UI.

## Tech Stack

- **Backend:** Python, Django, Django REST Framework
- **Frontend:** React, TypeScript, Vite
- **Database:** SQLite
- **Python package manager:** uv

## Project Structure

- `backend/` — API, models, business logic, import command, and tests
- `frontend/` — React application

## Data Model

`Contract` stores the original bound slip only. It does not store the calculated as-amended position; that will be derived from the slip and its endorsements.

Assumptions:
- `mga_reference` is unique across contracts.
- `currency` is an ISO-style three-letter uppercase ASCII code (e.g. `USD`).
- `sum_insured` and `gross_premium` are never negative. Negativity is checked before rounding, so `-0.001` is rejected. Accepted inputs are `Decimal` values, integers and decimal strings; floats, malformed text and non-finite values are rejected. Accepted amounts are rounded to two decimal places using `ROUND_HALF_UP` (e.g. `100.005` is stored as `100.01`, `100.004` as `100.00`) before validation and storage.
- `brokerage_pct` and `signed_line_pct` are between 0 and 100 inclusive.
- `expiry_date` is on or after `inception_date`; a same-day cover is allowed.
- `status` has a single allowed value, `BOUND`.
- Slip fields are immutable after creation. `Contract.save()` rejects changes to existing rows. This is application-level protection: `QuerySet.update()`, bulk operations that modify existing rows, and raw SQL bypass it and must not be used to change slip data.

### Endorsements

`Endorsement` records a numbered change to a `Contract`. Each endorsement belongs to one contract (`contract.endorsements`), and deleting a contract that has endorsements is blocked.

- `endorsement_number` is unique within a contract and starts at 1. The same number may be used by different contracts.
- `premium_change` is signed: positive increases premium, negative reduces it. Values are rounded to two decimals using `ROUND_HALF_UP`, so `-100.005` is stored as `-100.01`. It may be empty only for `CANCELLATION`; `create_endorsement()` calculates the refund for every cancellation and ignores any amount supplied by the caller.
- `changes` must be a JSON object. `{}` is valid. Its contents are checked by the type-specific validator described below, not by the model.
- Endorsements have no immutability rule yet.

Validation has two layers:

- **Structural model validation** runs in `Endorsement.save()` through `full_clean()`. It covers the contract link, the number range and uniqueness, choice fields, required dates and amounts, and the rule that `changes` is a JSON object.
- **Type-specific validation** is `validate_endorsement_changes(endorsement_type, changes)` in `contracts/services.py`. It returns a fresh normalized dictionary and does not query or write the database. It is called by `create_endorsement()`, not by `save()`.
  - `CHANGE_DETAILS` requires exactly `insured_name`: a string, trimmed, not blank, and at most 255 characters.
  - `CHANGE_SUM_INSURED` requires exactly `sum_insured`: rounded half-up to two decimals, rejected if negative, and returned as a fixed two-decimal string within the field capacity.
  - `EXTENSION` requires exactly `expiry_date` in canonical `YYYY-MM-DD` form. Whether it extends the current cover is not checked yet.
  - `PREMIUM_ADJUSTMENT` and `CANCELLATION` require an empty `changes` object.
  - Missing keys and unexpected keys are both rejected. Unexpected keys are reported by name so that stray payload fields cannot be stored silently.

### Contract Position

`calculate_position(contract, endorsements, as_at)` in `contracts/services.py` calculates a read-only position for a date. The caller loads the records; the function does not query or write the database.

- Only `AGREED` endorsements with `effective_date <= as_at` are applied. The effective date is inclusive. `recorded_date` is not used for filtering, so backdated endorsements apply from their effective date.
- Nothing is applied when `as_at` is before the contract's inception date.
- Endorsements are applied in ascending `endorsement_number`, regardless of input order or effective-date order. When two changes touch the same field, the higher number wins.
- A cancellation sets the status to `CANCELLED`, sets the cancellation date, and ends expiry the day before. Its stored `premium_change` is applied. A missing refund raises `ValueError`; it is never treated as zero.
- Financial rounding uses `ROUND_HALF_UP` to two decimals. Gross premium is rounded first. `net_premium` is gross after brokerage, and `our_net_premium` is calculated from the unrounded net share and then rounded, so net is not rounded before the share is calculated.

### Cancellation Return Premium

`calculate_cancellation_premium_change(contract, endorsements, effective_date)` returns the negative `premium_change` for a cancellation. It does not save anything.

- The pre-cancellation position is calculated from all non-cancellation endorsements using `calculate_position()`, so the gross premium and expiry date reflect only agreed changes effective on or before the cancellation date.
- The pre-cancellation expiry is the contract expiry, or the expiry set by an agreed extension effective on or before the cancellation date.
- Formula: `refund = gross * unused_days / total_days`, where `total_days = (expiry - inception).days + 1` and `unused_days = (expiry - effective_date).days + 1`. The result is rounded `ROUND_HALF_UP` to two decimals and returned as a negative value.
- A zero gross returns `0.00`. A date before inception, a date after the pre-cancellation expiry, or a negative gross raises `ValueError`.
- The helper does not check cancellation eligibility; `create_endorsement()` applies those rules before it calls the helper.

### Endorsement Creation

`create_endorsement(mga_reference, data)` in `contracts/services.py` is the only supported way to create an endorsement. It validates the candidate, checks the business rules against the contract's existing endorsements, and saves in a transaction. Failures raise `ValidationError` keyed by field, and nothing is written. Concurrent creation is not protected against.

Rules, with the error key each one reports:

- **Contract**: `mga_reference` must match an existing contract (`mga_reference`).
- **Number**: `endorsement_number` must be unused for the contract (`endorsement_number`).
- **Changes**: validated by the type-specific validator; for `EXTENSION`, the proposed expiry must be later than the current expiry (`changes`).
- **Current expiry**: the original expiry after all existing agreed non-cancellation endorsements. Drafts do not extend cover.
- **Effective date**: must be on or between inception and the current expiry, inclusive, for drafts and agreed candidates alike (`effective_date`).
- **Cancellations**: the refund is calculated from the stored history and any caller-supplied amount is ignored. A second agreed cancellation is rejected (`type`). Once an agreed cancellation exists, candidates effective on or after its date are rejected (`effective_date`). An agreed cancellation is rejected if it would leave existing agreed endorsements effective on or after its date (`effective_date`). Draft cancellations store a refund but do not affect positions or block other endorsements.
- **Financial safety**: for an agreed candidate, gross premium is replayed at every distinct effective date in the combined agreed history, applying endorsements in number order. Any negative intermediate or final gross is rejected (`premium_change`). Drafts are not replayed.

Assumptions:

- A stored cancellation refund is fixed when it is saved. Later backdated endorsements do not recalculate it.
- The duplicate-number check runs before model validation so that the error is field-level.
- Malformed or unexpected keys in `data` are rejected by field name.

## Read API

Three read endpoints under `/api/`, accepting `GET` only; other methods return `405`. Creation endpoints are described in the Write API section below. Positions are calculated on each request and never stored. "Today" is `timezone.localdate()`. Money is returned as fixed two-decimal strings, dates as ISO strings, and `cancellation_effective_date` is `null` unless the position is cancelled.

- `GET /api/contracts/` returns today's position for every contract, ordered by `mga_reference`. There is no pagination.
- `GET /api/contracts/<mga_reference>/` returns `slip` (the original contract fields), `endorsements` (every endorsement including drafts, in number order), and `current_position` (today's position). Unknown references return `404`.
- `GET /api/contracts/<mga_reference>/position/?as_at=YYYY-MM-DD` returns the position on that date. Omitting `as_at` uses today. An empty, malformed or non-canonical value returns `400` with an `as_at` field error. Unknown references return `404`.

Example, `GET /api/contracts/MGA-2026-0001/position/?as_at=2026-06-15` with one agreed premium adjustment of `500.00` effective 2026-03-01:

```json
{
  "mga_reference": "MGA-2026-0001",
  "as_at": "2026-06-15",
  "insured_name": "Acme Logistics Ltd",
  "status": "BOUND",
  "inception_date": "2026-01-01",
  "expiry_date": "2026-12-31",
  "cancellation_effective_date": null,
  "currency": "USD",
  "sum_insured": "1000000.00",
  "gross_premium": "120500.00",
  "net_premium": "108450.00",
  "our_net_premium": "27112.50",
  "applied_endorsements": [1]
}
```

Example, `GET /api/contracts/MGA-2026-0001/`:

```json
{
  "slip": {
    "mga_reference": "MGA-2026-0001",
    "insured_name": "Acme Logistics Ltd",
    "class_of_business": "Marine Cargo",
    "inception_date": "2026-01-01",
    "expiry_date": "2026-12-31",
    "currency": "USD",
    "sum_insured": "1000000.00",
    "gross_premium": "120000.00",
    "brokerage_pct": "10.00",
    "signed_line_pct": "25.00",
    "status": "BOUND"
  },
  "endorsements": [
    {
      "number": 1,
      "type": "PREMIUM_ADJUSTMENT",
      "status": "AGREED",
      "effective_date": "2026-03-01",
      "recorded_date": "2026-02-15",
      "premium_change": "500.00",
      "changes": {},
      "reason": "Adjust premium for additional exposure"
    }
  ],
  "current_position": {
    "mga_reference": "MGA-2026-0001",
    "as_at": "2026-06-15",
    "insured_name": "Acme Logistics Ltd",
    "status": "BOUND",
    "inception_date": "2026-01-01",
    "expiry_date": "2026-12-31",
    "cancellation_effective_date": null,
    "currency": "USD",
    "sum_insured": "1000000.00",
    "gross_premium": "120500.00",
    "net_premium": "108450.00",
    "our_net_premium": "27112.50",
    "applied_endorsements": [1]
  }
}
```

## Write API

Two creation endpoints under `/api/`. Both accept JSON. Unknown fields, including `id`, are rejected with a field error. Validation and business rules come from the model and `create_endorsement()`; the input serializers only check structure and types.

Money inputs must be decimal strings or integers. JSON floats and booleans are rejected. Strings such as `"100.005"` are kept exact and rounded half-up by the model or service.

- `POST /api/contracts/` creates a contract and returns the slip with `201`. `status` is optional; the only valid value is `BOUND`.
- `POST /api/contracts/<mga_reference>/endorsements/` creates an endorsement and returns it with `201`. `endorsement_number`, `type`, `status`, `effective_date`, `recorded_date` and `reason` are required. `changes` defaults to `{}`. `premium_change` may be omitted or `null` only for `CANCELLATION`. A cancellation's refund is always calculated by the server, and any supplied amount is ignored.

Example, `POST /api/contracts/` with `{"mga_reference": "MGA-2026-0001", "insured_name": "Acme Logistics Ltd", "class_of_business": "Marine Cargo", "inception_date": "2026-01-01", "expiry_date": "2026-12-31", "currency": "USD", "sum_insured": "1000000.00", "gross_premium": "120000.00", "brokerage_pct": "10.00", "signed_line_pct": "25.00"}` returns `201` with the slip, including `"status": "BOUND"`.

Example, `POST /api/contracts/MGA-2026-0001/endorsements/`:

```json
{
  "endorsement_number": 1,
  "type": "PREMIUM_ADJUSTMENT",
  "status": "AGREED",
  "effective_date": "2026-03-01",
  "recorded_date": "2026-02-15",
  "premium_change": "-100.005",
  "reason": "Premium correction"
}
```

returns `201` with `"premium_change": "-100.01"`.

Errors are `400` with one list of messages per field, for example:

```json
{
  "effective_date": ["Effective date must be between 2026-01-01 and 2026-12-31."]
}
```

Unknown contracts on the endorsement route return `400` with an `mga_reference` error. Unsupported methods return `405`.

## Sample Data Import

`backend/sample_data/` contains a sample contract file and a sample endorsement file. Import them from `backend/`:

```bash
uv run python manage.py import_data sample_data/contracts.json sample_data/endorsements.json
```

Both files are read and checked for valid JSON and top-level arrays before anything is written. Contracts are imported first, then endorsements, each in file order. Each row runs in its own transaction, so one rejected row does not stop the rest. Each rejection prints the row number, the reference, and the field-level reasons.

On an empty database the sample produces:

- Contracts: 3 loaded, 1 rejected (`MNK-PR-2026-004`, expiry before inception).
- Endorsements: 7 loaded, 4 rejected (row 5 effective after the cancellation, row 9 duplicate number 3, row 10 before inception, row 11 unknown contract).

The import never overwrites or deletes. Running it again on the same database loads nothing: 0 contracts loaded and 4 rejected, and 0 endorsements loaded and 11 rejected. Not every rejection is a duplicate. Three contract rows and eight endorsement rows are rejected as duplicate references or numbers; the remaining rows (contract row 4, endorsement rows 5, 10 and 11) fail their own validation rules again. Existing records are unchanged.

## Contracts List (Frontend)

The React app shows one row per contract from `GET /api/contracts/`, in reference order. Each row shows the current insured name, status, cover period, currency and gross premium, as returned by the backend. The UI does not calculate premiums or infer statuses. Money is displayed as the exact string returned, with two decimals.

The page has four states: loading, empty (`No contracts found.`), error (with a Retry button), and the contracts table. Setup and import instructions are kept in this README rather than in the UI. Requests are cancelled when the component unmounts, so cancelled requests do not show errors or update state.

Each reference is a button. Selecting one opens the contract detail (`GET /api/contracts/<reference>/`), and "Back to contracts" returns to the list. The detail shows:

- The original slip: reference, class of business, insured name, status, cover dates, currency, sum insured, gross premium, brokerage percentage and signed-line percentage.
- A position panel for a selected date. It starts with the current position from the detail response, so no extra request is made when the detail opens. Changing the date fetches `GET /api/contracts/<reference>/position/?as_at=YYYY-MM-DD`. Clearing the date sends no request and shows "Select a date to view the position." Dates before inception or after expiry are allowed.
- Comparison with the original slip. Insured name, status, cover dates, currency, sum insured and gross premium are compared by their API strings. A differing value is shaded and labelled "Changed". Net premium and our net premium have no original figure in the slip, so they are shown without comparison.
- Endorsement history in number order, with an Application status column. DRAFT rows are always "Not applied". AGREED rows show "Applied" or "Not applied on selected date" for the selected date. While the position is loading, failed or cleared, AGREED rows show no application status.

Stale results are not shown. Each date change replaces the previous position immediately with a loading state and cancels the request in flight. A response is shown only when its `as_at` matches the selected date. Detail requests are cancelled when the detail view is left.

### Adding an endorsement

The contract detail has an "Add endorsement" form, which posts to `POST /api/contracts/<reference>/endorsements/`. The form suggests the next endorsement number from the history, and the number remains editable. The type selector shows the matching fields only:

- Change details: new insured name.
- Change sum insured: new sum insured.
- Extension: new expiry date.
- Premium adjustment: no extra field.
- Cancellation: no premium field. The page shows "Return premium is calculated automatically." The server calculates the refund.

Premium changes are entered as signed decimal text and sent as strings. Dates are entered explicitly, and the form does not restrict them, so backdated entries are allowed. The frontend does not calculate any premium or refund.

Only the fields for the selected type are sent, and the form never sends stale values from another type. Basic checks (required fields, a positive whole endorsement number) run in the browser. Business rules come from the backend. A 400 response is shown next to the matching field. Changes errors appear next to the visible type-specific field, or next to the type selector when no such field is shown. Contract and other errors appear in an alert. Entered values are kept after a failure. A new submission or a type change clears the previous errors. Submission is disabled while the request is in progress, and failed requests are not retried automatically.

After a successful save, the form resets and the page shows "Endorsement added." The history and the position for the selected date are reloaded. A cleared comparison date stays cleared, and no position is fetched for it. If the save succeeds but the refresh fails, the success message stays visible with a "Retry refresh" button, and the page does not suggest submitting again.

Status: endorsement creation from the detail screen is implemented. Editing or deleting existing endorsements and contract creation from the UI are not implemented.

The page is built with Bootstrap CSS only, imported once in `frontend/src/main.tsx`.

## Setup

### Prerequisites

- Python 3.11 or later
- Node.js 18 or later
- [uv](https://docs.astral.sh/uv/) for Python package management

### Install Backend Dependencies

```bash
cd backend
uv sync --locked
```

### Install Frontend Dependencies

```bash
cd frontend
npm ci
```

## Development

Run the backend and frontend in **separate terminal windows**.

### Backend

```bash
cd backend
uv run python manage.py migrate
uv run python manage.py runserver
```

The API will be available at `http://127.0.0.1:8000/`.

### Frontend

```bash
cd frontend
npm run dev
```

The application will be available at `http://127.0.0.1:5173/` with API requests proxied to the backend.

## Testing

### Backend Tests

```bash
cd backend
uv run python manage.py test
```

### Frontend Build

```bash
cd frontend
npm run build
```

## Status

Phase 1: Reproducible backend and frontend setup complete.
