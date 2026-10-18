# Contract Endorsement Engine: Backend

Django REST API for contract slips, endorsements and dated positions. The root [README](../README.md) has the full setup, design and API reference.

## Commands

Run these from the `backend` folder.

```bash
uv sync --locked
uv run python manage.py migrate
uv run python manage.py import_data sample_data/contracts.json sample_data/endorsements.json
uv run python manage.py runserver
uv run python manage.py test
```

The development database is `db.sqlite3` in this folder. It is git-ignored. Use a separate settings module with a different `NAME` for disposable databases.

## Structure

- `config/`: Django project settings, root URL configuration and WSGI/ASGI entry points. `ALLOWED_HOSTS` is `localhost` and `127.0.0.1`.
- `contracts/models.py`: `Contract` (original slip) and `Endorsement` (numbered change), with model validation and the application-level slip immutability check.
- `contracts/services.py`: position calculation, cancellation refunds, endorsement changes validation and `create_endorsement()`.
- `contracts/serializers.py`: explicit input and output serializers for the API.
- `contracts/views.py` and `contracts/urls.py`: the five API operations under `/api/`.
- `contracts/management/commands/import_data.py`: sample import with per-row rejection reasons.
- `contracts/tests.py`: model, service, API and import tests.
- `sample_data/`: the sample contract and endorsement files.

## Notes

- The project uses SQLite for local development only. Production would need a database that stores decimals exactly, environment-based settings for `SECRET_KEY` and `DEBUG`, and authentication. None of these are configured.
- Known open issue: one test in `contracts/tests.py` (`test_amended_premium_totals_exceed_model_precision`) fails during setup on SQLite. See the root README, Status section.
