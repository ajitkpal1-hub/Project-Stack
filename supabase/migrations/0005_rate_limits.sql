-- Phase 9: usage limits for the expensive and abusable endpoints (AI scans, assistant
-- questions, reports, sign-in attempts). Shared by every server instance.
-- Run once in the Supabase SQL editor (Dashboard -> SQL Editor -> New query -> paste -> Run).
--
-- Keys are hashed on the server before they get here: no raw IP addresses are stored.
-- Only the server (service role) can call the function or see the table.

create table if not exists public.rate_limits (
  key text not null check (char_length(key) <= 120),
  window_start timestamptz not null,
  hits integer not null default 0,
  primary key (key, window_start)
);
create index if not exists rate_limits_window_idx on public.rate_limits (window_start);

alter table public.rate_limits enable row level security;  -- no policies: server only

-- Count one hit in the current window and say whether it is still within the limit.
create or replace function public.hit_rate_limit(p_key text, p_limit integer, p_window_seconds integer)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  w timestamptz := to_timestamp(floor(extract(epoch from now()) / p_window_seconds) * p_window_seconds);
  n integer;
begin
  insert into public.rate_limits (key, window_start, hits) values (p_key, w, 1)
  on conflict (key, window_start) do update set hits = public.rate_limits.hits + 1
  returning hits into n;
  if random() < 0.01 then  -- occasional tidy-up of old windows
    delete from public.rate_limits where window_start < now() - interval '2 days';
  end if;
  return n <= p_limit;
end
$$;

revoke all on function public.hit_rate_limit(text, integer, integer) from public, anon, authenticated;
grant execute on function public.hit_rate_limit(text, integer, integer) to service_role;
