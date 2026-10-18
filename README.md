# Contract Endorsement Engine

A Django REST API and React application for recording original insurance contract slips and their numbered endorsements, and for calculating the as-amended position of a contract on any date.

## Features

- Store original contract slips; the slip itself is not edited after creation.
- Record numbered endorsements for cover changes, premium adjustments, extensions and cancellations.
- Calculate a contract's position on a selected date, including the premium and net figures.
- Apply agreed endorsements in number order; drafts are stored but never applied.
- Calculate cancellation return premiums with exact decimal arithmetic.
- Import sample data with clear, per-row rejection reasons.
- Browse contracts, compare the original slip with the position on a selected date, and add endorsements from the detail screen.

## Tech Stack

- **Backend:** Python 3.11+, Django 5.2, Django REST Framework 3.16
- **Frontend:** React 18, TypeScript, Vite, Bootstrap 5 CSS
- **Database:** SQLite (local development)
- **Package managers:** uv (Python), npm (frontend)

## Project Structure

- `backend/`: Django project (`config/`), `contracts` app (models, services, serializers, views, management command, tests) and `sample_data/`.
- `frontend/`: React application (`src/components/`, `src/api.ts`, `src/types.ts`).

## Setup

Prerequisites: Python 3.11 or later, [uv](https://docs.astral.sh/uv/), and Node.js 18 or later with npm.

Run the backend from the `backend` folder. Each command below starts from the repository root, so you can paste the blocks in order.

**Terminal 1: backend**

```bash
cd backend
uv sync --locked
uv run python manage.py migrate
uv run python manage.py import_data sample_data/contracts.json sample_data/endorsements.json
uv run python manage.py runserver
```

The API is then available at `http://127.0.0.1:8000/api/contracts/`.

**Terminal 2: frontend** (from the repository root)

```bash
cd frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:5173/`. Vite proxies `/api` requests to the backend on port 8000, so both terminals must be running.

### Tests and build

```bash
cd backend
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test
```

```bash
cd frontend
npm run build
```

### Sample data

`import_data` reads both files and checks that they are valid JSON arrays before writing anything. It imports contracts first, then endorsements, each in file order. Each row runs in its own transaction, so one rejected row does not stop the others. Expected result on an empty database:

- Contracts: 3 loaded, 1 rejected (`MNK-PR-2026-004`, expiry before inception).
- Endorsements: 7 loaded, 4 rejected (row 5 after the cancellation, row 9 duplicate number 3, row 10 before inception, row 11 unknown contract).

The command never overwrites or deletes records. Running it again on the same database loads nothing: 0 contracts and 0 endorsements are loaded, and 4 contract rows and 11 endorsement rows are rejected. Eight endorsement rows are rejected as duplicate numbers; the others fail their own rules again. Existing records are unchanged.

## Data Model

**Why original slips and endorsements are separate.** A `Contract` records the slip as it was bound. Endorsements are later changes issued against it. Keeping them apart means the original terms are always visible, each change keeps its own dates and reason, and the current position is derived from the history rather than stored. Position figures are calculated on request and are never saved.

**Contract** holds the bound slip: reference (unique), insured name, class of business, inception and expiry dates, currency, sum insured, gross premium, brokerage and signed-line percentages, and a status that can only be `BOUND`. Monetary values are `Decimal` values rounded to two decimals.

**Endorsement** belongs to one contract and has a number unique within that contract, a type (`CHANGE_SUM_INSURED`, `CHANGE_DETAILS`, `PREMIUM_ADJUSTMENT`, `EXTENSION` or `CANCELLATION`), a status (`DRAFT` or `AGREED`), effective and recorded dates, a signed premium change, a `changes` JSON object and a reason. Deleting a contract that has endorsements is blocked.

Validation happens in three places:

- The model checks structure and field types when it saves.
- `validate_endorsement_changes()` checks the per-type `changes` payload.
- `create_endorsement()` applies the business rules against the contract's history.

**Slip immutability is application-level.** `Contract.save()` rejects any change to an existing slip. `QuerySet.update()`, bulk operations on existing rows and raw SQL bypass this check and must not be used to change slip data.

## Position Calculation

`calculate_position(contract, endorsements, as_at)` is a pure function over records the caller has already loaded.

- **Effective date:** only `AGREED` endorsements with `effective_date <= as_at` are applied. The effective date is inclusive. `recorded_date` is not used for filtering, so a backdated endorsement applies from its effective date. Nothing is applied before inception.
- **Application order:** applicable endorsements are applied in ascending `endorsement_number`, regardless of input order or effective-date order.
- **Conflicts:** when applicable changes touch the same field, the higher-numbered endorsement wins, even if its effective date is earlier. The implemented rule is number order. Changing it to effective-date order would make a later-recorded backdated change overrule a change the insurer issued after it, and it would need a tie-breaker for equal dates. The current rule is simple and reproducible, so it is the one implemented.
- **Expiry:** an extension changes the expiry from its effective date. A cancellation sets the status to `CANCELLED`, sets the cancellation date and ends expiry the day before. Positions past the expiry are not blocked.

## Rounding and Cancellation Rules

- All monetary results are rounded to two decimals with `ROUND_HALF_UP`. The sign is kept, so `-100.005` becomes `-100.01`.
- Gross premium is the original gross plus the stored premium changes of the applicable endorsements, rounded first.
- `net_premium = rounded_gross × (1 − brokerage_pct / 100)`.
- `our_net_premium = (unrounded net × signed_line_pct / 100)`, rounded. It is taken from the unrounded net, not the rounded net.
- The cancellation refund is `gross × unused_days / total_days`, where `total_days = (expiry − inception) + 1` and `unused_days = (expiry − cancellation_date) + 1`. The expiry used is the expiry in force on the cancellation date, including agreed extensions. The result is rounded half-up and returned as a negative `premium_change`.
- A zero gross returns `0.00`. A cancellation date before inception, after the pre-cancellation expiry, or a negative gross is rejected.

## Endorsement Creation Rules

Creation is available through `create_endorsement()`, the REST API and the detail screen. Each rule is checked against the stored history, and rejected requests write nothing.

- **Number:** unused for the contract (`endorsement_number`).
- **Current cover:** the original expiry after all existing agreed non-cancellation endorsements. Drafts do not extend cover.
- **Effective date:** between inception and the current expiry, inclusive, for drafts and agreed items alike (`effective_date`).
- **Extension:** the new expiry must be later than the current expiry (`changes`).
- **Cancellation:** a second agreed cancellation is rejected (`type`). Once an agreed cancellation exists, later candidates are rejected (`effective_date`). An agreed cancellation may not leave existing agreed endorsements effective on or after its date. The refund is calculated by the server, and any amount the caller supplies is ignored.
- **Premium safety:** for an agreed candidate, the gross is replayed at every effective date in the combined agreed history. A negative intermediate or final gross is rejected (`premium_change`). Drafts are not replayed.

## REST API

All endpoints are under `/api/`. Read endpoints accept `GET` only; the list route also accepts `POST`.

| Method and path | Purpose |
| --- | --- |
| `GET /api/contracts/` | Current positions for all contracts, ordered by reference. |
| `POST /api/contracts/` | Create a contract. `status` is optional and must be `BOUND`. Returns `201`. |
| `GET /api/contracts/<reference>/` | Original slip, endorsement history (including drafts) and the current position. |
| `GET /api/contracts/<reference>/position/?as_at=YYYY-MM-DD` | Position on the given date; defaults to today. `400` for a malformed date. |
| `POST /api/contracts/<reference>/endorsements/` | Create an endorsement. Returns `201`, or `400` with field-level errors. |

Example creation request:

```json
{
  "endorsement_number": 5,
  "type": "PREMIUM_ADJUSTMENT",
  "status": "AGREED",
  "effective_date": "2026-06-01",
  "recorded_date": "2026-06-02",
  "premium_change": "500.00",
  "changes": {},
  "reason": "Premium adjustment for additional exposure"
}
```

Money inputs must be decimal strings or integers; JSON floats and booleans are rejected. Unknown fields are rejected. Error responses map each problem to the field it concerns:

```json
{
  "effective_date": ["Effective date must be between 2026-01-01 and 2026-12-31."]
}
```

Unknown contracts on the endorsement route return `400` with an `mga_reference` error. Unknown contracts on the read routes return `404`.

## Contracts Screens

The React app has three parts:

- **Contracts list:** one row per contract with its current insured name, status, cover period, currency and gross premium. Each reference opens the detail screen.
- **Contract detail:** the original slip beside the position for a selected date. Changed values are shaded and labelled "Changed". The date input starts from the current position's date. Clearing it stops position requests. The endorsement history follows, with an application status for each row.
- **Add endorsement form:** shown on the detail screen. The form suggests the next number and shows only the fields for the selected type. The server's messages appear next to the matching field. While the history refreshes after a save, the form is disabled and the position and application indicators are hidden. Retry refresh repeats only GET requests.

The frontend does not calculate premiums, refunds or statuses. Money is shown as the exact string from the API.

## Assumptions and Limitations

- **SQLite** is used for local development only. SQLite has no exact decimal type: `DecimalField` values are stored as floating-point numbers. Values beyond about 9.0 × 10^15 are not guaranteed to read back exactly, and Django's SQLite converter can then fail with `InvalidOperation`. The model accepts 18-digit amounts, so not every model-valid amount round-trips through SQLite. Python calculations still use `Decimal` throughout, and the position API returns calculated totals as exact strings even when they exceed the stored-field precision. PostgreSQL `NUMERIC` would be the preferred production monetary storage. The precision test uses amounts of 5 × 10^15 that SQLite can store exactly, and it checks the calculated totals of 10^16 without changing storage or serializer precision.
- **Slip immutability** is enforced in application code, not by the database. Direct updates bypass it.
- **Current cover** is interpreted as the original expiry plus agreed extensions. Dates are checked against it when an endorsement is created, not when a position is read.
- **Drafts** are stored and shown but never applied. A draft cancellation stores a refund but does not restrict other endorsements.
- **Stored refunds** are fixed when saved. Later backdated changes do not recalculate them, so a refund can differ from one calculated today.
- **Concurrency:** the rule checks and the save are not one atomic database operation. Two requests can pass the checks together. The database still rejects duplicate numbers, but other rules have no lock.
- **No authentication**, no endorsement editing or deletion, and no contract creation from the UI. The API is intended for local use.

## AI Question

A safer way to let an AI assistant use this data would be a read-only API or a narrow tool. It would accept only validated reference and date values and return typed, structured results. Access would be checked per contract, and each query would be logged for audit. This is a proposed design only: none of it is implemented, and this project does not provide security for an AI integration.

## AI Tools Used

- **Claude Code (Haiku model):** implementation of the backend, frontend and tests, in phased pull requests.
- **ChatGPT:** planning and review of the phases, as part of this project's workflow.

## What Would Improve With More Time

- Use PostgreSQL `NUMERIC` for monetary storage in production, so every model-valid amount round-trips exactly.
- Add browser tests for the contract screens and the endorsement form.
- Add endorsement editing and voiding, with an audit trail of changes.
- Add authentication and contract-level permissions.
- Make creation atomic under concurrent requests, for example with row locks.
- Add pagination to the contract list.

## Status

- Backend: contract and endorsement models, position calculation, creation rules, REST API, sample import and tests are implemented.
- Frontend: contracts list, detail with date comparison, and endorsement form are implemented. `npm run build` passes.
- Backend tests: `uv run python manage.py test` runs 126 tests, all passing, in a clean checkout of the verification branch. `check` and `makemigrations --check --dry-run` report no issues.
- Sample import on an empty disposable database: 3 contracts loaded and 1 rejected; 7 endorsements loaded and 4 rejected. Re-importing loads nothing and leaves the records unchanged.
- API smoke checks against a new disposable database: 31 of 31 passed. They cover the five API operations, date filtering, number order, drafts, the Harbour cancellation refund of -35671.23, the Marine extension and backdated adjustment, field-level 400 errors, 404 for unknown contracts, and unchanged records after rejected requests.
- Frontend: `npm ci` and `npm run build` pass in a clean checkout.
- **Browser verification has not been performed.** Both the list-to-detail screens and the endorsement form are unverified in a real browser. The checklist below is the manual test to run before submission. HTTP checks and a passing build are not browser checks.

### Manual browser checklist

Run both terminals from Setup, using a disposable database, and check:

1. The list shows three contracts; selecting Harbour opens its detail, and "Back to contracts" returns to the list.
2. Harbour shows the original name "Harbour Logistics Ltd" and the amended name "Harbour Logistics Group Ltd" with a "Changed" label.
3. The date 2025-12-31 shows no endorsements applied and the original gross.
4. 2026-09-29 shows BOUND; 2026-09-30 shows CANCELLED with expiry 2026-09-29.
5. A DRAFT row is labelled "Not applied" on every date.
6. Typing dates quickly always shows the position for the last date entered, and clearing the date shows "Select a date to view the position."
7. Switching the endorsement type shows only the matching fields. A cancellation hides the premium input and shows the automatic-return-premium note.
8. A duplicate endorsement number or an invalid date shows an error next to that field, and the entered values are kept.
9. A successful save adds a row to the history, keeps the selected date, and updates the suggested number.
10. The form is disabled while the save is in progress, and it stays disabled while the refresh runs.
11. Stopping the backend and pressing Retry shows an error, and Retry works after the backend restarts.
12. At a narrow width, the tables scroll horizontally and the comparison columns stack.
