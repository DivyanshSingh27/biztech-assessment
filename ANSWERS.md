# Architecture Review Answers

## A. Django Admin Performance with 500,000+ Rows

Django Admin can become slow when a table contains more than 500,000 rows, especially when the admin page loads related objects, performs expensive searches, or calculates counts across large datasets. I would first profile the page to identify whether the main bottleneck is database queries, Python processing, or rendering.

My first change would be to reduce unnecessary database work. I would use `list_select_related` for foreign-key relationships displayed in the list and carefully chosen `prefetch_related` for many-to-many or reverse relationships. I would avoid calling related managers or expensive model properties inside `list_display` methods when those operations generate additional queries. Frequently used filters and search fields should have suitable database indexes, selected according to actual query plans and workload.

Next, I would make the admin list more selective. I would configure `list_display`, `list_filter`, `search_fields`, and `list_per_page` to show only useful information. For very large tables, I would consider disabling the full result count using Django Admin's supported paginator customization, where appropriate, because exact counts can be expensive. I would also evaluate search behavior and avoid broad, unindexed substring searches on large tables.

For operational safety, I would consider read-only or restricted admin access for high-volume tables and provide a dedicated reporting interface for complex analytics instead of making the admin responsible for every reporting query.

Finally, I would measure before and after using query profiling and representative data. I would compare response time, query count, query execution plans, and database load. I would not assume that adding indexes alone solves the issue; the changes should be based on the measured bottleneck.

## B. Offset Pagination vs. Cursor Pagination

Offset pagination uses a page number or offset to retrieve records. It is straightforward to implement and allows users to jump to a specific page. However, large offsets can become expensive because the database may need to scan or skip many rows before returning the requested page. Concurrent inserts or deletes can also cause records to shift between pages, leading to duplicates or missed records during navigation.

Cursor pagination instead uses a stable ordering and a cursor representing the last-seen position. For example, an API can order records by creation time and a unique ID, then request records after the last returned pair. The database can use an appropriate index to find the next page without skipping every earlier row. Cursor pagination is generally a better choice for large, frequently updated datasets and continuous feeds.

Cursor pagination has trade-offs. It usually does not support jumping directly to an arbitrary page number, and the cursor must encode or reference the ordering position safely. The ordering should be deterministic; if timestamps can repeat, a unique tie-breaker such as the primary key is necessary. The cursor should also be validated and, where appropriate, signed to prevent clients from manipulating pagination state.

For a small administrative table where users need page numbers and random page access, offset pagination may be sufficient. For high-volume order APIs or activity feeds, I would prefer cursor pagination with a matching composite index, such as `(created_at, id)`, assuming the query filters and ordering align with that index.

I would validate the choice using realistic data volumes and query plans. The decision should consider navigation requirements, consistency during concurrent writes, index design, and the expected access pattern rather than treating either approach as universally superior.
