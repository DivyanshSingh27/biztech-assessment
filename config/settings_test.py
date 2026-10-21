from .settings import *  # noqa: F401,F403

# Separate Redis database so tests never touch development data.
REDIS_URL = "redis://localhost:6379/1"
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL

# Small window so 500 jobs finish in about 10 seconds.
EMAIL_RATE_LIMIT = 100
EMAIL_RATE_WINDOW_SECONDS = 2

# File-based test database: the worker thread and the test thread both use it.
DATABASES["default"]["TEST"] = {"NAME": str(BASE_DIR / "test_db.sqlite3")}  # noqa: F405
DATABASES["default"]["OPTIONS"] = {"timeout": 20}  # noqa: F405
