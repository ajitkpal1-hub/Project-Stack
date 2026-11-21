-- Management reporting: anonymous usage counts + weekly views for the Coefficient dashboard.
-- Run once in the Supabase SQL editor (Dashboard -> SQL Editor -> New query -> paste -> Run).
--
-- usage_events: one row per classification (website scan or voice). Date, channel, bin lane and
--   area only. Never a photo, text, IP, account or anything that identifies a person.
--   Written only by the server (service role); RLS on with no policies, so nobody else can read it.
-- reporting schema: weekly COUNTS only (no names, phones, addresses or descriptions). Not exposed
--   through the Supabase API. The reloop_reporting role can read these views and nothing else.
-- The login password for reloop_reporting is NOT in this file: set it yourself (see docs/DASHBOARD.md).

create table if not exists public.usage_events (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  channel text not null check (channel in ('web_scan', 'voice')),
  lane text not null check (lane in ('wet', 'dry', 'reuse', 'textile', 'e-waste', 'hazardous', 'medical', 'unsure')),
  area text not null default 'not_given' check (area in ('dombivli', 'thakurli', 'kalyan', 'other', 'not_given'))
);
create index if not exists usage_events_created_idx on public.usage_events (created_at);
alter table public.usage_events enable row level security;
revoke all on public.usage_events from anon, authenticated;

create schema if not exists reporting;
revoke all on schema reporting from public, anon, authenticated;

-- PIN codes the team has checked, mapped to an area. Starts empty on purpose: add only PINs you have
-- confirmed, e.g.  insert into reporting.area_pins values ('421201', 'Dombivli');
create table if not exists reporting.area_pins (
  pin_code text primary key check (pin_code ~ '^[1-9][0-9]{5}$'),
  area text not null check (area in ('Dombivli', 'Thakurli', 'Kalyan'))
);

-- Area from what the donor typed: the locality name first (Thakurli before Dombivli, since
-- "Thakurli, Dombivli East" names both), then a confirmed PIN code, else 'Other / not given'.
create or replace function reporting.area_of(p_locality text, p_pin text)
returns text
language sql
stable
security definer  -- reads area_pins as its owner, so the reporting role never needs that table
set search_path = reporting, pg_temp
as $$
  select case
    when p_locality ilike '%thakurli%' then 'Thakurli'
    when p_locality ilike '%dombivli%' or p_locality ilike '%dombivali%' then 'Dombivli'
    when p_locality ilike '%kalyan%' then 'Kalyan'
    else coalesce((select a.area from reporting.area_pins a where a.pin_code = p_pin), 'Other / not given')
  end
$$;

create or replace function reporting.area_label(p_area text)
returns text
language sql
immutable
as $$
  select case p_area
    when 'dombivli' then 'Dombivli'
    when 'thakurli' then 'Thakurli'
    when 'kalyan' then 'Kalyan'
    else 'Other / not given'
  end
$$;

-- Weeks start on Monday, in India time.
create or replace view reporting.weekly_donations as
select
  (date_trunc('week', l.created_at at time zone 'Asia/Kolkata'))::date as week_start,
  reporting.area_of(l.locality, l.pin_code) as area,
  l.category,
  count(*) as listed,
  count(*) filter (where l.status in ('available', 'reserved', 'completed')) as approved,
  count(*) filter (where l.status = 'completed') as completed,
  count(*) filter (where l.status = 'rejected') as rejected
from public.donation_listings l
group by 1, 2, 3;

create or replace view reporting.weekly_classifications as
select
  (date_trunc('week', e.created_at at time zone 'Asia/Kolkata'))::date as week_start,
  reporting.area_label(e.area) as area,
  case e.channel when 'web_scan' then 'Website scan' else 'Voice helper' end as channel,
  e.lane,
  count(*) as classifications
from public.usage_events e
group by 1, 2, 3, 4;

-- One row per week and area: the numbers management asks for first.
create or replace view reporting.weekly_summary as
with d as (
  select week_start, area, sum(listed) as donations_listed, sum(approved) as donations_approved,
         sum(completed) as donations_completed
  from reporting.weekly_donations group by 1, 2
), c as (
  select week_start, area, sum(classifications) as classifications,
         sum(classifications) filter (where lane in ('hazardous', 'medical')) as hazardous_or_medical
  from reporting.weekly_classifications group by 1, 2
)
select
  coalesce(d.week_start, c.week_start) as week_start,
  coalesce(d.area, c.area) as area,
  coalesce(c.classifications, 0) as classifications,
  coalesce(c.hazardous_or_medical, 0) as hazardous_or_medical_classifications,
  coalesce(d.donations_listed, 0) as donations_listed,
  coalesce(d.donations_approved, 0) as donations_approved,
  coalesce(d.donations_completed, 0) as donations_completed
from d full outer join c on c.week_start = d.week_start and c.area = d.area
order by 1 desc, 2;

-- Read-only login for Coefficient: these three views and nothing else.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'reloop_reporting') then
    create role reloop_reporting nologin;  -- docs/DASHBOARD.md: set a password and LOGIN yourself
  end if;
end
$$;
grant usage on schema reporting to reloop_reporting;
grant select on reporting.weekly_donations, reporting.weekly_classifications, reporting.weekly_summary to reloop_reporting;
revoke execute on function reporting.area_of(text, text), reporting.area_label(text) from public;
grant execute on function reporting.area_of(text, text), reporting.area_label(text) to reloop_reporting;
revoke all on reporting.area_pins from reloop_reporting;
alter role reloop_reporting set statement_timeout = '15s';
