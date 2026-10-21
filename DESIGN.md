# Design: Rate-Limited Async Email Queue

## 1. Problem and numbers
During a flash sale the system receives 2,000 order-confirmation email requests within 10 seconds. The email provider allows 200 emails per minute (about 3.33 per second). If the limiter paces sends evenly, only about 33 emails can go out during the first 10 seconds; the rest must wait. The exact first-10-seconds number depends on the rate-limiter algorithm (Section 4).

Draining 2,000 emails at 200/min takes at least 10 minutes, assuming the provider is always available and there are no retries.

So "handling the burst in under 10 seconds" means accepting and enqueuing the requests, not sending them. The API must not call the provider directly: 2,000 synchronous calls would block request threads and time out, and any provider rate-limit rejection would lose the email with no retry.

Instead, the API enqueues a job and returns immediately. Celery workers process the queue at a controlled rate, using Redis to coordinate the rate limit across all workers. A job accepted into the queue is durably stored, but that does not mean the email was delivered.

## 2. Options considered
### 2.1 Celery + Redis
**Pros**
- Retry with backoff: `autoretry_for` selects which exceptions trigger a retry, `retry_backoff` makes the delay exponential, and `max_retries` stops unlimited retries.
- Crash resilience: with `acks_late=True` the broker message is acknowledged only after the task finishes. If a worker dies mid-task, the message is redelivered instead of lost.
- Mature and widely used, with monitoring tools and a large community.

**Cons**
- Operational overhead: besides the Django app, Redis and Celery workers must be run and monitored.
- Celery's built-in `rate_limit` is per worker instance, not global. Three workers each set to 200/min could send 600/min together. So I build a shared Redis rate limiter that all workers consult (Section 4).
- Redis as a broker is not durable by default. A Redis crash can lose queued jobs unless AOF persistence (`appendonly yes`) is enabled.
- With `acks_late=True`, a redelivered task can run twice, so an email could be sent twice. Tasks need an idempotency key. On a Redis broker, an unacknowledged message from a killed worker is redelivered only after `visibility_timeout` (default 1 hour), which must be tuned (Section 5).
### 2.2 Django Q / Django Q2
**Pros**
- Simpler infrastructure with the ORM broker: Django Q2 can use Django's database as its task broker, so a separate Redis service is not required. This reduces setup and operational overhead for smaller applications.
- Retry controls: Django Q2 provides `retry` and `max_attempts`. Note that `retry` is how long the broker waits before presenting an unacknowledged task again; it is not exponential backoff for provider errors.
- Multiple broker options: besides the Django ORM it supports Redis and other brokers, so the choice can follow the infrastructure.

**Cons**
- Database contention: with the ORM broker, workers poll and lock task rows in the same database as application queries (unless a separate database is configured), and every task state change is a database write. A burst of 2,000 jobs adds database load while the provider can only accept 200 emails per minute.
- Rate limiting still needs custom work: the documented retry settings do not enforce a global 200/min limit across workers. A shared rate limiter would still be needed, and any backoff mechanism would have to be verified against the selected Django Q2 version.
- Maintenance: the original `django-q` project's development stalled, and Django Q2 is a separate fork. Its current maintenance, supported versions, security fixes and release activity should be checked before adopting it.
### 2.3 Custom implementation
**Pros**
- Full control over job storage, scheduling, rate limiting and retry behaviour.
- Can be tailored to the exact requirements without adopting a complete task-processing framework.

**Cons**
- Crash safety is my job. A plain Redis `BRPOP` removes the job from the list, so a worker that dies right after popping loses it. A safe version needs `LMOVE` into a per-worker processing list plus a recovery process for stale entries.
- I would also need to implement and test retries, backoff, dead-letter handling and monitoring.
- More custom code means more failure cases to investigate and maintain, which conflicts with the instruction not to over-engineer.
## 3. Decision
I chose Celery with Redis. It gives retries with exponential backoff (`autoretry_for`, `retry_backoff`) and crash safety (`acks_late`) out of the box, so I do not have to build and test them myself. Redis is both the broker and the shared store for the rate limiter. Neither Celery nor Django Q enforces a global 200/min limit, so I write that part myself with an atomic Redis operation, so concurrent workers cannot exceed the limit together. Jobs that exhaust their retries go to a separate dead-letter store.
## 4. Rate limiter
## 5. Reliability (retries, dead letters, worker crash)
## 6. Redis failure behaviour
## 7. Known limitations
