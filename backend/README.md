# Contract Endorsement Engine — Backend

Local-development scaffold for the Django REST API.

## Requirements

- Python 3.11 or later
- [uv](https://docs.astral.sh/uv/) for dependency management

## Setup

### Install Dependencies

```bash
uv sync
```

### Apply Migrations

```bash
uv run python manage.py migrate
```

### Run Development Server

```bash
uv run python manage.py runserver
```

The API will be available at `http://127.0.0.1:8000/`.

### Run Tests

```bash
uv run python manage.py test
```

## Project Structure

- `manage.py` — Django management script for tasks like migrations, running the server, and test execution.
- `config/` — Django project package containing settings, URL routing, and ASGI/WSGI application setup.
  - `settings.py` — Configuration for installed apps (including `rest_framework` and `contracts`), middleware, databases (SQLite), and REST framework defaults.
  - `urls.py` — Root URL configuration; routes API endpoints under `/api/`.
  - `asgi.py` — ASGI application for async deployment.
  - `wsgi.py` — WSGI application for traditional deployment.
- `contracts/` — Django app for contract and endorsement management.
  - `models.py` — `Contract` model for original bound slips.
  - `admin.py` — Django admin interface (to be implemented).
  - `views.py` — API viewsets (to be implemented).
  - `serializers.py` — DRF serializers for API schemas (to be implemented).
  - `urls.py` — App-specific URL routing (to be implemented).
  - `tests.py` — Contract validation and immutability tests.

## Notes

This is a local-development scaffold. Production deployment will require:
- Environment-based settings for `DEBUG`, `SECRET_KEY`, and `ALLOWED_HOSTS`.
- Database migration to PostgreSQL or another production database.
- Static file serving and media storage configuration.
- Authentication and permissions middleware.
- CORS configuration for frontend integration.
