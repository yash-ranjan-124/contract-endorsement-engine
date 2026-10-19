# Contract Endorsement Engine

## Overview

A Django REST API and React application for managing insurance contracts and their numbered endorsements. View the original contract, calculate its as-amended position on a selected date, and add changes through a simple interface.

## Installation

### Prerequisites

- Python 3.11 or later
- [uv](https://docs.astral.sh/uv/)
- Node.js 18 or later with npm

### Clone the repository

```bash
git clone https://github.com/yash-ranjan-124/contract-endorsement-engine.git
cd contract-endorsement-engine
```

### Backend

From the repository root, run in your first terminal:

```bash
cd backend
uv sync --locked
uv run python manage.py migrate
uv run python manage.py import_data sample_data/contracts.json sample_data/endorsements.json
uv run python manage.py runserver
```

API: http://127.0.0.1:8000/api/contracts/

The sample files include deliberately invalid rows. The import reports rejection reasons and continues loading valid records. Existing records are not overwritten.

### Frontend

Open a second terminal at the repository root:

```bash
cd frontend
npm ci
npm run dev
```

Application: http://127.0.0.1:5173/

Keep both servers running. Vite forwards `/api` requests to the Django backend.

### Run tests

From the repository root:

```bash
cd backend
uv run python manage.py test
```

The backend suite covers position calculations, validation rules, cancellation refunds, sample imports and API behavior.

## Project Details

### Technology

- **Backend:** Django 5.2 and Django REST Framework 3.16
- **Frontend:** React 18, TypeScript, Vite and Bootstrap 5 CSS
- **Database:** SQLite for local development

### Contracts and endorsements

A contract stores the original signed slip: insured name, cover dates, currency, sum insured, gross premium, brokerage and signed-line percentages. The original slip remains unchanged after creation.

Each endorsement belongs to a contract and has a unique number within that contract, a type, status, effective date, recorded date, premium adjustment, type-specific `changes` JSON object and reason. A database constraint enforces unique numbers per contract; a foreign key protects contracts with endorsement history from deletion.

Separating the original slip from its endorsements preserves the signed terms and change history. The position is derived from these records, so there is no separate position table to keep synchronized. Model validation handles field constraints, while a shared service handles endorsement business rules for both API requests and sample imports.

Supported changes:

- Change the insured name.
- Change the sum insured.
- Adjust the premium.
- Extend the cover period.
- Cancel cover with a calculated return premium.

### Position calculation

The position on a selected date is calculated from the original slip and all `AGREED` endorsements effective on or before that date. Changes are applied in endorsement-number order. `DRAFT` endorsements remain visible in history but do not affect the position.

Positions are calculated on demand rather than stored. Python `Decimal` arithmetic and half-up rounding are used for monetary calculations. Cancellation refunds use inclusive day counts and are stored as negative premium adjustments.

### Application screens

- **Contracts list:** current insured name, status, cover period, currency and gross premium.
- **Contract detail:** original slip and selected-date position side by side, with changed values highlighted and endorsement history shown in number order.
- **Endorsement form:** fields change with the selected type, validation messages appear beside the relevant fields, and history and position refresh after saving.

### API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/contracts/` | List current contract positions. |
| POST | `/api/contracts/` | Create an original contract slip. |
| GET | `/api/contracts/{reference}/` | Retrieve the slip, endorsements and current position. |
| GET | `/api/contracts/{reference}/position/?as_at=YYYY-MM-DD` | Calculate the position on a date; defaults to today. |
| POST | `/api/contracts/{reference}/endorsements/` | Add an endorsement. |

### Structure

- `backend/config/`: Django configuration and root URLs.
- `backend/contracts/`: models, business services, serializers, API views and import command.
- `backend/sample_data/`: contract and endorsement JSON files.
- `frontend/src/`: React components, API functions and TypeScript types.

## Assumptions and Design Decisions

- **SQLite:** chosen to keep local setup small and dependency-free. It does not provide native fixed-point decimal storage, so some high-significance monetary values can lose precision when persisted. Calculations use Python `Decimal`; PostgreSQL `NUMERIC` would be the production choice.
- **Slip immutability:** enforced by `Contract.save()` and the absence of update endpoints. Direct SQL, `QuerySet.update()` and bulk updates can bypass this application-level protection.
- **Dates and cover:** effective dates are inclusive. Before inception, the API returns the original slip with no endorsements applied. Queries after expiry remain valid. On creation, current cover uses the original expiry as amended by all existing agreed extensions; drafts do not extend it.
- **Recorded date:** retained as history but does not filter the position. A backdated endorsement applies from its effective date, even if recorded later. The optional `known_at` feature is not implemented.
- **Cancellation:** cover ends the day before cancellation. Inclusive day counts and the expiry in force on the cancellation date determine the refund. A second agreed cancellation, or one that would invalidate existing agreed endorsements effective on or after it, is rejected. Draft cancellations do not restrict later endorsements.
- **Stored refunds:** the server calculates and stores the cancellation premium change at creation, ignoring a caller-supplied amount. Later backdated endorsements do not recalculate an existing refund.
- **Premium safety and rounding:** an agreed candidate is checked across effective dates and endorsement-number prefixes so gross premium never becomes negative. Amounts use two-decimal half-up rounding. Both net figures are calculated from rounded gross; our net uses the unrounded net intermediate before its final rounding.
- **Concurrency:** creation uses a transaction and a database uniqueness constraint, but does not serialize concurrent history validation with per-contract locks.
- **Scope:** no authentication, endorsement editing/deletion, or contract-creation screen. Contract creation is available through the API.

## Rule Question: Backdated Changes to the Same Field

The effective date decides whether an endorsement is eligible; its number decides the application order. If endorsement #1 changes the insured name to B from March and #2 changes it to C from February, February shows C. March also shows C because #2 is applied after #1, despite its earlier effective date.

This follows rule 3 exactly. I would keep the supplied rule for this implementation and clarify the intended precedence with the business before changing it. If the business instead wanted the latest effective change to win, a separately agreed rule could order by effective date and then number as a tie-breaker; that would change historical query results.

## AI Question: Safe Read Access

An AI agent could use a read-only position API or a narrow MCP tool accepting only a validated contract reference and date. The backend would enforce authentication and contract-level authorization, calculate the position using the existing service, and return structured data with the query date and applied endorsement numbers. The agent would have no direct database access or write tools; requests would be audited and contract text treated as data rather than instructions. These controls are a proposed integration, not features implemented in this local application.

## AI Tools Used

- **Claude Code with Haiku 5.5:** used for writing backend and frontend code, tests and documentation in small implementation steps.
- **ChatGPT:** used for requirements discussion, implementation planning and code review.

## Improvements With More Time

- Move monetary storage to PostgreSQL `NUMERIC`.
- Add per-contract locking and concurrency tests for endorsement creation.
- Add browser tests for navigation, date changes, form validation and refresh behavior.
- Add authentication and contract-level permissions before exposing the API.
- Add the optional `known_at` query for positions based on information recorded by a given date.
- Clarify the refund policy for later backdated endorsements and add an explicit adjustment workflow if required.
