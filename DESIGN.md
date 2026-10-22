
# Design: Rate-Limited Async Email Queue

## 1. Problem and numbers

During a flash sale, the system receives 2,000 order-confirmation email requests within 10 seconds. The email provider allows 200 emails per minute, equivalent to an average of about 3.33 emails per second.

At that rate, only about 33 emails can be sent during the first 10 seconds if sending is paced evenly. The exact number depends on the limiter algorithm and initial quota state. Draining 2,000 emails requires at least 10 minutes of provider capacity, assuming no retries or downtime.

Therefore, accepting the burst within 10 seconds means accepting and enqueueing the requests, not delivering every email within that time. The API should enqueue work and return promptly rather than call the provider synchronously.

## 2. Options considered

### 2.1 Celery + Redis

**Advantages**

- Celery provides task execution, queue integration, acknowledgement controls, and retry primitives.
- Redis can act as the broker and as shared storage for a global rate limiter.
- The ecosystem has established monitoring and operational tools.

**Disadvantages**

- Django, Redis, and Celery workers must be operated and monitored.
- Celery's built-in rate limit is per worker instance, not a shared global quota. Multiple workers therefore need a separate shared limiter.
- Redis broker durability depends on persistence and deployment configuration. Persistence reduces the risk of losing queued work but does not guarantee zero data loss in every failure scenario.
- Late acknowledgements can result in redelivery and duplicate execution. They do not guarantee exactly-once email delivery.

### 2.2 Django Q / Django Q2

**Advantages**

- Django Q2 can use the Django ORM as a task broker, reducing the need for separate broker infrastructure in some deployments.
- It supports task execution and retry-related configuration.
- Multiple broker choices can fit different infrastructure requirements.

**Disadvantages**

- An ORM broker can increase database writes and polling load alongside application queries.
- A global provider quota still requires shared rate-limiting logic.
- Retry semantics and compatibility depend on the selected version and broker configuration.
- Maintenance status, supported Django versions, and security updates should be checked before adoption.

### 2.3 Custom queue implementation

**Advantages**

- Complete control over job storage, scheduling, retry behaviour, and rate limiting.
- Can be tailored to a specific workload.

**Disadvantages**

- Reliable queue processing requires recovery of jobs claimed by workers that crash.
- A plain Redis `BRPOP` removes a job from the queue before processing; a worker crash can lose it unless a recovery mechanism is added.
- Retries, exponential backoff, dead-letter handling, monitoring, and recovery all become application responsibilities.
- This increases implementation and maintenance risk.

## 3. Decision

I chose Celery with Redis. Celery provides task execution and acknowledgement mechanisms, while the task code implements provider retries with exponential backoff and a five-attempt limit. Redis is used both as the broker and as the shared rate-limiter store.

The application implements a custom atomic sliding-window limiter because the provider's 200-per-minute limit must apply across all workers collectively. Jobs that exhaust provider retries are marked `DEAD` in the database.

The design targets prompt acceptance of the burst and controlled asynchronous delivery. Successful enqueueing is not the same as successful delivery.

## 4. Rate limiter

### 4.1 Why a sliding window?

The requirement is a strict maximum of 200 sends in any rolling 60-second period. A token bucket with capacity 200 can allow a burst of 200 immediately and then additional sends as tokens refill. A fixed-window counter can also allow nearly 400 sends across a minute boundary.

A sliding-window limiter checks reservations within the previous 60 seconds and admits a new reservation only when the quota permits it. This directly represents the rolling-window requirement.

The trade-off is that the limiter stores one sorted-set entry per reservation and performs more Redis operations than a simple counter. At a quota of 200, the active set is small.

### 4.2 Atomicity

The limiter uses a Redis Lua script to remove expired entries, count active reservations, and record an allowed reservation as one atomic operation. Redis executes the script without interleaving another client's commands.

The script uses Redis server time so workers do not depend on their individual system clocks. Each reservation has a unique member, preventing two reservations in the same millisecond from overwriting each other.

The expiry on the key is for cleanup when it becomes idle; the sorted-set window logic enforces the quota.

### 4.3 Redis failure policy: fail closed

The limiter fails closed: if it cannot obtain a reservation, the task must not send an email without authorization. Redis errors follow a retry path rather than bypassing the limiter.

Because Redis is also the broker, an outage can prevent new jobs from being enqueued and can disrupt workers' access to queued messages. The API should report an enqueue failure rather than claim that the email was accepted.

Failing closed protects against unmetered sending but cannot guarantee new jobs will be accepted during a broker outage.

## 5. Reliability: retries, dead letters, and worker crashes

### 5.1 Provider retries

When the provider raises `ProviderError`, the task increments `EmailJob.attempts` and stores the error in `last_error`. Before the fifth failed provider attempt, it retries with an exponential delay calculated as `min(2 ** attempts, 300)` seconds. At five failures, the job is marked `DEAD`.

This provider retry limit is implemented in application code using the database attempt counter. It does not rely on Celery's `autoretry_for` configuration.

Redis errors follow a separate retry path with a five-second countdown. Celery's retry counter is unlimited for this task, while provider failures are bounded by `MAX_PROVIDER_ATTEMPTS`.

Rate-limit denials do not increment the provider attempt count because the provider was not called.

### 5.2 Dead-letter handling

After five provider failures, the existing `EmailJob` row becomes the dead-letter record through its `DEAD` status and stored error. This avoids operating a second dead-letter queue and makes failed jobs queryable from the database.

Requeueing a dead job after the cause is fixed is currently a manual operation. Automated dead-letter review and replay tooling are not included.

### 5.3 Rate-limit denial

When the limiter denies a reservation, the task schedules another message using `apply_async(countdown=...)` rather than blocking a worker with `time.sleep()`. The countdown includes the limiter's retry delay and random jitter to spread out simultaneous retries.

The provider attempt counter is not incremented. A task may be rescheduled multiple times while waiting for quota.

There is a possible duplicate-message window if a replacement message is published but the current task's completion is not acknowledged. The database status check helps skip jobs that are no longer pending, but it does not make the database and broker update atomic.

### 5.4 Worker termination and redelivery

The task sets `acks_late=True`, so acknowledgement occurs after task execution rather than immediately when execution starts. `reject_on_worker_lost=True` requests requeueing when a worker child process is lost.

For a Redis broker, an unacknowledged task can be redelivered after the configured visibility timeout. The project configures a 120-second timeout. That value must be evaluated against the maximum task runtime and countdown behaviour: if it is too short, a message can become eligible for redelivery while the original execution is still active.

`worker_prefetch_multiplier=1` limits how many messages a worker reserves ahead of processing. On redelivery, the task checks the `EmailJob` status and skips jobs that are no longer pending.

These settings improve recovery but do not by themselves prove crash recovery works in every scenario. A worker-termination test should verify redelivery and ensure that a completed job is not sent again.

### 5.5 Delivery guarantee

This is at-least-once task processing, not exactly-once email delivery. If the provider accepts an email but the worker dies before `status=SENT` is saved, a later redelivery can send the email again. A task that runs longer than the visibility timeout can also overlap with a redelivery.

Provider-supported idempotency keys would reduce duplicate-delivery risk where available. The limiter reservation is consumed before the provider call, so failed attempts can use quota; this is conservative with respect to the provider limit.

## 6. Redis failure behaviour

Redis has two roles: the Celery broker and the shared rate-limiter store. An outage can affect both queue operations and authorization to send.

The task does not bypass the limiter when Redis is unavailable. It retries Redis errors, while enqueue failures should be surfaced by the API. Redis persistence and recovery settings should be selected for the deployment's durability requirements and tested under failure.

A production deployment should monitor Redis availability, queue depth, the age of the oldest queued job, retry volume, and dead-letter count. Recovery procedures should cover restoring Redis, checking pending jobs, and safely replaying dead-lettered work.

## 7. Known limitations

- Email delivery is not exactly once. A provider can accept a message before the application records success, creating a possible duplicate on retry.
- Saving an `EmailJob` and publishing its Celery message are not one atomic operation. A transactional outbox would improve recovery from failures between those steps.
- Redis broker durability depends on persistence and failover configuration. The rate-limit state and queue state should be tested across restarts and failures.
- Dead-lettered jobs require manual review and requeueing; operational replay tooling is not implemented.
- A worker-crash recovery test should be run and recorded before claiming that a `SIGKILL` scenario has been experimentally verified.
- The ORM benchmark measures local SQLite query counts. It demonstrates query reduction, not reproduction of the reported production latency regression or proof of a particular production response-time improvement.
