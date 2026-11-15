-- Phase 7: directory of recycling centres, collectors and donation partners.
-- Run once in the Supabase SQL editor (Dashboard -> SQL Editor -> New query -> paste -> Run).
--
-- Nothing here is invented: every entry is added by an admin with a source link, or
-- suggested by a member and hidden until an admin verifies it.
--   * Everyone can read verified entries.
--   * A signed-in member can suggest a place (status 'pending') and see their own suggestions.
--   * Verifying, editing and removing go through the server (service role) after an admin check.

create table if not exists public.partners (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 2 and 120),
  kind text not null check (kind in (
    'recycler', 'ewaste_collector', 'scrap_dealer', 'ngo', 'hazardous_collection',
    'biomedical', 'collection_point', 'repair', 'other'
  )),
  materials text[] not null default '{}',            -- waste lanes accepted: wet, dry, e-waste, ...
  donation_categories text[] not null default '{}',  -- for NGOs: clothes, books, toys, ...
  address text not null default '' check (char_length(address) <= 300),
  locality text not null check (char_length(locality) between 2 and 80),
  city text not null default '' check (char_length(city) <= 80),
  pin_code text not null check (pin_code ~ '^[1-9][0-9]{5}$'),
  phone text not null default '' check (char_length(phone) <= 40),      -- the organisation's public number
  website text not null default '' check (website = '' or website ~* '^https?://'),
  source_url text not null default '' check (source_url = '' or source_url ~* '^https?://'),
  latitude double precision check (latitude between -90 and 90),
  longitude double precision check (longitude between -180 and 180),
  status text not null default 'pending' check (status in ('verified', 'pending', 'rejected')),
  submitted_by uuid references auth.users (id) on delete set null,
  verified_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (status <> 'verified' or source_url <> '')   -- a verified entry always names its source
);

create index if not exists partners_status_pin_idx on public.partners (status, pin_code);
create index if not exists partners_materials_idx on public.partners using gin (materials);

drop trigger if exists partners_touch on public.partners;
create trigger partners_touch before update on public.partners
  for each row execute function public.touch_updated_at();

alter table public.partners enable row level security;

drop policy if exists "partners: read verified or own suggestion" on public.partners;
create policy "partners: read verified or own suggestion" on public.partners
  for select to anon, authenticated
  using (status = 'verified' or submitted_by = auth.uid());

drop policy if exists "partners: members suggest" on public.partners;
create policy "partners: members suggest" on public.partners
  for insert to authenticated
  with check (submitted_by = auth.uid() and status = 'pending' and verified_at is null);
