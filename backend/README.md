# Contract Endorsement Engine Backend

Django REST API for original contract slips, numbered endorsements and date-based contract positions.

See the [project README](../README.md) for prerequisites, installation, application features and API endpoints.

## Run

From the `backend/` folder:

```bash
uv sync --locked
uv run python manage.py migrate
uv run python manage.py import_data sample_data/contracts.json sample_data/endorsements.json
uv run python manage.py runserver
```

The backend uses a local SQLite database and serves the API at http://127.0.0.1:8000/api/contracts/.
