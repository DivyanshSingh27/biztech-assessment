# BizTech Analytics Assessment

## Overview

This repository contains a Django application with an asynchronous email
queue using Celery and Redis, a Redis-backed sliding-window email rate
limiter, and an order-summary API demonstrating Django ORM optimization.

## Requirements

- Python 3.12 (or a compatible supported version)
- Redis
- Git

## Local setup

1. Activate your Python environment.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt

   ```
3. Start Redis and verify it responds with `PONG`:

   `redis-cli ping`

4. Apply migrations:

   `python manage.py migrate`

5. Run checks and tests:

   `python manage.py check`
   `pytest -q`
   `python manage.py test orders`

6. Start the server:

   `python manage.py runserver`

## Endpoints

- Order summary: `GET /api/orders/summary/`
- Django admin: `/admin/`
- Django Silk profiler: `/silk/`

## ORM benchmark

See `evidence/orm-benchmark.md` for the query-count measurements and limitations.

The local SQLite experiment reduced the query count from 401 to 1 for 200 orders. This does not establish that the production latency regression was reproduced.

## Evidence

- `evidence/orm-benchmark.md` — benchmark details.
- `evidence/silk-optimized.png` — optimized endpoint profiling screenshot.

## Security

Do not commit production credentials or secrets. The Django development server is for local development only.
