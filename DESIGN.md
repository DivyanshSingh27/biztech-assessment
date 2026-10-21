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
### 4.1 Why a sliding window?
I chose a sliding window over a token bucket because the requirement is a strict maximum of 200 emails in any rolling 60-second period. A token bucket with capacity 200 and a refill of 200 per minute can send 200 immediately and then roughly 200 more from refill within the same 60 seconds, so it can pass about 400 in a rolling minute. A fixed window (`INCR` + `EXPIRE`) is simpler, but can also allow almost 400 emails across a minute boundary, for example 200 at 12:00:59 and another 200 at 12:01:00. A sliding window checks the previous 60 seconds on every request, so it matches the required limit directly.

Trade-off: it stores one sorted-set entry per allowed send (at most 200 here, which is small) and does more Redis work per request than a counter.

### 4.2 Atomicity
The limiter uses a Redis Lua script (`SLIDING_WINDOW_LUA`) that removes expired entries (`ZREMRANGEBYSCORE`), counts the rest (`ZCARD`) and records an allowed request (`ZADD`) as one atomic operation. Redis runs commands one at a time on its command-processing thread, so another worker cannot interleave its own check halfway through the script. For example, if Worker A and Worker B both see four entries under a limit of five, separate Python `ZCARD` and `ZADD` calls could let both through; the script lets the first through and rejects the second. The script reads time from Redis (`TIME`) so workers with different system clocks agree, and uses a unique member per request (`uuid4`) so two sends in the same millisecond are not collapsed into one entry. `PEXPIRE` only cleans up an idle key; it does not enforce the limit.

### 4.3 Redis failure policy: fail closed
I choose fail closed because exceeding the provider's limit could cause HTTP 429 responses or account restrictions. If Redis is unavailable, the email task must not send without rate-limit authorization. The limiter call raises `redis.exceptions.ConnectionError`, which the task treats as retryable so Celery tries again when Redis recovers. However, Redis is also the Celery broker, so during an outage new tasks may fail to enqueue and workers may be unable to fetch or acknowledge tasks. The API should return an error (HTTP 503) when enqueueing fails instead of pretending the email was accepted. Fail closed prevents unmetered sending, but it cannot guarantee that new jobs can be queued during a broker outage.

## 5. Reliability (retries, dead letters, worker crash)
### 5.1 Provider retries
If the provider raises `ProviderError`, the task increments `EmailJob.attempts` and stores the error in `last_error`. It retries with exponential backoff of `2 ** attempts` seconds, capped at 300 seconds, and stops after `MAX_PROVIDER_ATTEMPTS = 5`. Rate-limit denials do not increment this counter. Celery's own `max_retries` is `None` because Celery's counter only covers Redis outages (fail closed, retry after 5 seconds); provider failures are capped by `attempts`.

### 5.2 Dead-letter handling
After five provider failures the task sets `status=DEAD` and keeps `last_error`. I use the existing `EmailJob` row as the dead-letter record instead of a separate Redis queue: the status and error stay queryable (`EmailJob.objects.filter(status=DEAD)`, backed by the index on `status`) without another queue to operate. Requeueing a dead job after the cause is fixed is a manual step; I did not build tooling for it.

### 5.3 Rate-limit denial
When the limiter returns `allowed=False`, the task schedules a new message with `apply_async(countdown=...)` instead of blocking a worker with `time.sleep()`. It does not increment `attempts`, because the provider was not called and the email has not failed. Random jitter (0-5 seconds) spreads out jobs that were denied together. The new message is enqueued before the current task returns, so a crash in between can cause a duplicate message but not a lost job; the status check below absorbs the duplicate.

### 5.4 Worker SIGKILL
The task uses `acks_late=True`, so the broker message is acknowledged after the task finishes, not when it starts. Two cases:
- Whole worker killed (`kill -9` on the main process): the message stays in Redis's `unacked` hash and is redelivered after `visibility_timeout`. I set it to 120 seconds instead of the 1-hour default, and it must stay above the longest countdown (about 65 seconds), otherwise Redis would redeliver countdown tasks that are merely waiting.
- Only a pool child process lost (for example killed for memory) while the worker survives: `reject_on_worker_lost=True` makes Celery requeue the message instead of acknowledging it.

`worker_prefetch_multiplier=1` limits how many unacknowledged messages a worker holds ahead of processing, so a killed worker blocks fewer jobs. On redelivery the task checks `EmailJob.status` and returns `skipped:SENT` if the email already went out.

Verified manually: after `kill -9` the message stayed in the `unacked` hash, was redelivered after the visibility timeout, and the redelivered task returned `skipped:SENT` without sending again.

### 5.5 Delivery guarantee
This is at-least-once processing, not exactly-once delivery. If the provider accepts an email and the worker dies before `status=SENT` is saved, or a provider call outlives `visibility_timeout` and the message is redelivered while still running, the recipient can get a duplicate. The limiter slot is taken before the provider call, so a failed attempt also uses a slot; this errs on the safe side of the provider limit.

## 6. Redis failure behaviour
## 7. Known limitations
