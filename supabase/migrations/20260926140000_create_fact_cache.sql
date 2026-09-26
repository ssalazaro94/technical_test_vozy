-- Cache of validated language model extractions.
--
-- cache_key is a SHA-256 fingerprint of the prompts (agent specification,
-- customer record, call date and every turn), the response schema and the
-- model. An identical conversation reuses its facts without a model call; any
-- change yields another key. Same schema and RLS policy as the audit tables.

create table callaudit.fact_cache (
    cache_key  text primary key check (cache_key ~ '^[0-9a-f]{64}$'),
    model      text not null,
    facts      jsonb not null,
    created_at timestamptz not null default now()
);

alter table callaudit.fact_cache enable row level security;
