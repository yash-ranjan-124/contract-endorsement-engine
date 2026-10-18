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

Three read-only endpoints under `/api/`. Only `GET` is accepted; other methods return `405`. Positions are calculated on each request and never stored. "Today" is `timezone.localdate()`. Money is returned as fixed two-decimal strings, dates as ISO strings, and `cancellation_effective_date` is `null` unless the position is cancelled.

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
