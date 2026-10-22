# ORM Performance Investigation

## Environment
- Framework: Django 6.1.2
- Database: SQLite (local development)
- Dataset: 200 orders examined, 500 order items, 1 customer
- Profiling tools: Django Silk 5.6.0 and Django query logging

## Results

| Measurement | Baseline ORM | Optimized ORM |
|---|---:|---:|
| Orders processed | 200 | 200 |
| SQL query count | 401 | 1 |
| Query-count reduction | — | 99.75% |

## Baseline
The baseline loads orders, then accesses each order's customer and items
inside a loop. This causes one initial query plus additional queries for
each order's customer and items, producing 401 queries for 200 orders.

## Optimization
The optimized query uses `select_related("customer")` and database-side
aggregation with `Count`, `Sum`, and `ExpressionWrapper`. It returned
200 orders and calculated the first order's item count as 2 and total as
125 using one SQL query.

## Limitations
These are measured local SQLite query counts, not production latency
measurements. The test does not reproduce the reported 80 ms to 30 s
incident, and no before/after elapsed-time claim is made here. SQLite
timings should not be treated as representative of PostgreSQL production
performance.

## Profiling evidence
Django Silk recorded a request to `/api/orders/summary/`. Save screenshots
of the baseline and optimized query measurements here when available.
