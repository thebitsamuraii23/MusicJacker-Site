# Refactor guide — MusicJacker-Site

This repository contained a large single-file Flask app. The following changes/scaffolding were applied to start a maintainable, scalable architecture.

Overview of the new structure (partial, example):

- routes/ — Flask blueprints (route handlers only: parse/validate, delegate to services)
- services/ — business logic and orchestration (yt-dlp, download orchestration, tasks)
- downloaders/ — adapters for downloaders (yt-dlp centralization)
- converters/ — FFmpeg wrapper and conversion logic
- metadata/ — mutagen-based tag application helpers
- utils/ — exceptions, storage drivers and shared helpers
- schemas/ — pydantic schemas for request validation
- workers/ — Celery worker configuration and tasks

Example components added in this refactor:
- `routes/download.py` — example blueprint for `/api/download_audio` using `DownloadService`
- `services/download_service.py` — orchestrates info checks and session management
- `services/yt_dlp_service.py` — centralized calls to yt-dlp and caching
- `converters/ffmpeg_service.py` — small FFmpeg wrapper class
- `workers/celery_app.py` and `services/tasks.py` — Celery app and example conversion task
- `utils/storage.py` — local temp storage driver with TTL
- `utils/exceptions.py` — custom exceptions
- `schemas/download.py` — pydantic request schema

How to run workers (development):

1. Start Redis (required by Celery): `redis-server`
2. Start a Celery worker from project root:

```bash
export PYTHONPATH=$(pwd)
celery -A workers.celery_app.celery worker --loglevel=info
```

How the example `/api/convert` now works:
- If Celery is configured, the conversion is enqueued as a Celery task (safer, isolated worker process, retries).
- If Celery isn't present, the app falls back to the legacy thread-based conversion to avoid breaking behavior.

Notes and next steps (recommended):

1. Replace in-process temporary filesystem usage with S3/MinIO driver (implement S3StorageDriver in `utils/storage.py`).
2. Move long business logic out of `app.py` into `services/` (complete the remaining routes: search, playlist, metadata)
3. Add robust task result -> status updates in Redis/DB (to track progress and status from workers)
4. Replace in-memory caches with Redis and implement TTLs.
5. Add authentication tokens for file delivery URLs (signed URLs) — minimize direct file exposure.
6. Add IP rate limiting middleware (Flask-Limiter or reverse-proxy rules) and upload size limits.
7. Consider moving to FastAPI if you need async endpoints and a modern type-first architecture.

If you'd like, I can continue by completing the refactor for additional routes and add tests for the new service classes.
