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
- `premium_change` is signed: positive increases premium, negative reduces it. Values are rounded to two decimals using `ROUND_HALF_UP`, so `-100.005` is stored as `-100.01`. It may be empty only for `CANCELLATION`; the cancellation calculation that fills it in is not implemented yet.
- `changes` must be a JSON object. `{}` is valid. Its contents are not validated yet.
- Business rules are deferred: cover-date checks, type-specific validation of `changes`, and position calculations are not enforced by the model.
- Endorsements have no immutability rule yet.

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
- The helper assumes the cancellation is otherwise eligible; restrictions on existing cancellations are not checked here.

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
