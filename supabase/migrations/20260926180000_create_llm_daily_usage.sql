-- Daily count of language model calls, the service's own spending guard.
--
-- Each call to the model first increments today's row atomically; above the
-- configured budget the service stops calling the model until the next day.
-- It lives in the database because the web service restarts when the free
-- plan puts it to sleep, and an in-memory counter would reset.

create table callaudit.llm_daily_usage (
    day   date primary key,
    calls integer not null default 0 check (calls >= 0)
);

alter table callaudit.llm_daily_usage enable row level security;
