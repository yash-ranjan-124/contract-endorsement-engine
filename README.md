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

## Project Details

### Technology

- **Backend:** Django 5.2 and Django REST Framework 3.16
- **Frontend:** React 18, TypeScript, Vite and Bootstrap 5 CSS
- **Database:** SQLite for local development

### Contracts and endorsements

A contract stores the original signed slip: insured name, cover dates, currency, sum insured, gross premium, brokerage and signed-line percentages. The original slip remains unchanged after creation.

Each endorsement belongs to a contract and has a unique number within that contract, a type, status, effective date, recorded date, premium adjustment and reason.

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
