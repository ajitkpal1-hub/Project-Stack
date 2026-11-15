-- Phase 8: saved scans and answers, and reports about AI answers.
-- Run once in the Supabase SQL editor (Dashboard -> SQL Editor -> New query -> paste -> Run).
--
-- saved_items: what a signed-in member chose to keep. Never a photo. Each member can
--   read, add and delete only their own.
-- ai_flags: "report a problem" on a scan result or assistant answer. Written and read
--   only by the server (service role); admins review them in /admin/flags.

create table if not exists public.saved_items (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  kind text not null check (kind in ('scan', 'answer')),
  title text not null check (char_length(title) between 1 and 160),
  lane text,
  summary jsonb not null default '{}'::jsonb check (octet_length(summary::text) <= 20000),
  created_at timestamptz not null default now()
);
create index if not exists saved_items_user_idx on public.saved_items (user_id, created_at desc);

alter table public.saved_items enable row level security;

drop policy if exists "saved: read own" on public.saved_items;
create policy "saved: read own" on public.saved_items for select to authenticated using (user_id = auth.uid());
drop policy if exists "saved: add own" on public.saved_items;
create policy "saved: add own" on public.saved_items for insert to authenticated with check (user_id = auth.uid());
drop policy if exists "saved: delete own" on public.saved_items;
create policy "saved: delete own" on public.saved_items for delete to authenticated using (user_id = auth.uid());

create table if not exists public.ai_flags (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in ('scan', 'answer')),
  reason text not null check (reason in ('wrong_lane', 'unsafe', 'wrong_source', 'other')),
  note text not null default '' check (char_length(note) <= 500),
  snapshot jsonb not null default '{}'::jsonb check (octet_length(snapshot::text) <= 20000),
  reporter_id uuid references auth.users (id) on delete set null,
  status text not null default 'open' check (status in ('open', 'resolved')),
  admin_note text not null default '' check (char_length(admin_note) <= 300),
  created_at timestamptz not null default now(),
  resolved_at timestamptz
);
create index if not exists ai_flags_status_idx on public.ai_flags (status, created_at);

-- Enabled with no policies: only the server can read or write reports.
alter table public.ai_flags enable row level security;
