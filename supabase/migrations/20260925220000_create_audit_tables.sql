-- Audit storage for the call audit service.
--
-- A dedicated schema keeps these tables out of the Data API: Supabase only
-- exposes the "public" schema through PostgREST, so nothing here is reachable
-- with the project's anon key. Row level security is enabled as a second
-- barrier. The service connects as the database owner and is not affected.

create schema if not exists callaudit;

create table callaudit.audit_runs (
    run_id              uuid primary key,
    generated_at        timestamptz not null,
    rubric_version      text not null,
    model               text not null,
    total_conversations integer not null check (total_conversations > 0),
    average_score       numeric(5, 1) not null check (average_score between 0 and 100),
    report              jsonb not null,
    created_at          timestamptz not null default now()
);

create table callaudit.conversation_audits (
    audit_id        uuid primary key,
    run_id          uuid references callaudit.audit_runs (run_id) on delete cascade,
    run_position    integer,
    conversation_id text not null,
    call_date       date not null,
    analysis        text not null check (analysis in ('completo', 'parcial')),
    score           numeric(5, 1) not null check (score between 0 and 100),
    severity        text not null check (severity in ('ninguna', 'leve', 'grave', 'critica')),
    outcome         text,
    failed_criteria text[] not null,
    audit           jsonb not null,
    created_at      timestamptz not null default now(),
    -- An audit either belongs to a run (with its position) or stands alone.
    check ((run_id is null) = (run_position is null))
);

create index conversation_audits_run_idx on callaudit.conversation_audits (run_id, run_position);
create index conversation_audits_conversation_idx on callaudit.conversation_audits (conversation_id);
create index conversation_audits_failed_idx on callaudit.conversation_audits using gin (failed_criteria);

alter table callaudit.audit_runs enable row level security;
alter table callaudit.conversation_audits enable row level security;
