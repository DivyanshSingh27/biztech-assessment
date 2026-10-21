# Design: Rate-Limited Async Email Queue

## 1. Problem and numbers
During a flash sale the system receives 2,000 order-confirmation email requests within 10 seconds. The email provider allows 200 emails per minute (about 3.33 per second). If the limiter paces sends evenly, only about 33 emails can go out during the first 10 seconds; the rest must wait. The exact first-10-seconds number depends on the rate-limiter algorithm (Section 4).

Draining 2,000 emails at 200/min takes at least 10 minutes, assuming the provider is always available and there are no retries.

So "handling the burst in under 10 seconds" means accepting and enqueuing the requests, not sending them. The API must not call the provider directly: 2,000 synchronous calls would block request threads and time out, and any provider rate-limit rejection would lose the email with no retry.

Instead, the API enqueues a job and returns immediately. Celery workers process the queue at a controlled rate, using Redis to coordinate the rate limit across all workers. A job accepted into the queue is durably stored, but that does not mean the email was delivered.

## 2. Options considered
### 2.1 Celery + Redis
### 2.2 Django Q
### 2.3 Custom implementation
## 3. Decision
## 4. Rate limiter
## 5. Reliability (retries, dead letters, worker crash)
## 6. Redis failure behaviour
## 7. Known limitations
