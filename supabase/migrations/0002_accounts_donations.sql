-- Phase 6: accounts and donations.
-- Run once in the Supabase SQL editor (Dashboard -> SQL Editor -> New query -> paste -> Run).
--
-- Security model:
--   * The web server is the first line of defence: it checks who you are and what you
--     may do before every write. Status changes (approve, reserve, complete) are made by
--     the server with the service-role key, after those checks.
--   * Row-level security is the second line: with only a user's own token, a person can
--     read public listings and their own rows, create a listing in "pending_review", and
--     request an available item. They can never approve, reserve or edit anything directly.
--   * Hazardous and medical items have no donation category, so they can't be listed.
--   * Contact details live in profiles, readable only by their owner. The server shares a
--     contact note only with the other side of an approved request.

create extension if not exists pgcrypto;

-- ---------- profiles ----------
create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text not null default '' check (char_length(display_name) <= 60),
  locality text not null default '' check (char_length(locality) <= 80),
  pin_code text not null default '' check (pin_code = '' or pin_code ~ '^[1-9][0-9]{5}$'),
  contact_note text not null default '' check (char_length(contact_note) <= 200),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists profiles_touch on public.profiles;
create trigger profiles_touch before update on public.profiles
  for each row execute function public.touch_updated_at();

alter table public.profiles enable row level security;

drop policy if exists "profiles: read own" on public.profiles;
create policy "profiles: read own" on public.profiles
  for select to authenticated using (id = auth.uid());
drop policy if exists "profiles: insert own" on public.profiles;
create policy "profiles: insert own" on public.profiles
  for insert to authenticated with check (id = auth.uid());
drop policy if exists "profiles: update own" on public.profiles;
create policy "profiles: update own" on public.profiles
  for update to authenticated using (id = auth.uid()) with check (id = auth.uid());

-- ---------- donation listings ----------
create table if not exists public.donation_listings (
  id uuid primary key default gen_random_uuid(),
  donor_id uuid not null references auth.users (id) on delete cascade,
  title text not null check (char_length(title) between 3 and 80),
  category text not null check (category in (
    'clothes', 'books', 'toys', 'furniture', 'electronics', 'school_supplies', 'household_goods', 'other'
  )),
  condition text not null check (condition in ('works_clean', 'needs_repair')),
  description text not null default '' check (char_length(description) <= 1000),
  locality text not null check (char_length(locality) between 2 and 80),
  pin_code text not null check (pin_code ~ '^[1-9][0-9]{5}$'),
  photo_path text,
  status text not null default 'pending_review' check (status in (
    'pending_review', 'available', 'reserved', 'completed', 'rejected'
  )),
  rejection_reason text check (char_length(rejection_reason) <= 300),
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists donation_listings_status_idx on public.donation_listings (status, created_at desc);
create index if not exists donation_listings_donor_idx on public.donation_listings (donor_id);
create index if not exists donation_listings_pin_idx on public.donation_listings (pin_code);

drop trigger if exists donation_listings_touch on public.donation_listings;
create trigger donation_listings_touch before update on public.donation_listings
  for each row execute function public.touch_updated_at();

alter table public.donation_listings enable row level security;

drop policy if exists "listings: read public or own" on public.donation_listings;
create policy "listings: read public or own" on public.donation_listings
  for select to anon, authenticated
  using (status in ('available', 'reserved') or donor_id = auth.uid());

drop policy if exists "listings: create own, pending only" on public.donation_listings;
create policy "listings: create own, pending only" on public.donation_listings
  for insert to authenticated
  with check (donor_id = auth.uid() and status = 'pending_review' and reviewed_at is null and rejection_reason is null);
-- No update or delete policies: those go through the server (service role) after checks.

-- ---------- donation requests ----------
create table if not exists public.donation_requests (
  id uuid primary key default gen_random_uuid(),
  listing_id uuid not null references public.donation_listings (id) on delete cascade,
  requester_id uuid not null references auth.users (id) on delete cascade,
  message text not null default '' check (char_length(message) <= 500),
  status text not null default 'pending' check (status in ('pending', 'approved', 'declined', 'withdrawn')),
  decided_at timestamptz,
  created_at timestamptz not null default now(),
  unique (listing_id, requester_id)
);

create index if not exists donation_requests_listing_idx on public.donation_requests (listing_id);
create index if not exists donation_requests_requester_idx on public.donation_requests (requester_id);

alter table public.donation_requests enable row level security;

drop policy if exists "requests: read own or on own listing" on public.donation_requests;
create policy "requests: read own or on own listing" on public.donation_requests
  for select to authenticated
  using (
    requester_id = auth.uid()
    or exists (select 1 from public.donation_listings l where l.id = listing_id and l.donor_id = auth.uid())
  );

drop policy if exists "requests: create on available listing" on public.donation_requests;
create policy "requests: create on available listing" on public.donation_requests
  for insert to authenticated
  with check (
    requester_id = auth.uid()
    and status = 'pending'
    and decided_at is null
    and exists (
      select 1 from public.donation_listings l
      where l.id = listing_id and l.status = 'available' and l.donor_id <> auth.uid()
    )
  );

-- ---------- listing photos ----------
-- Private bucket: no storage policies, so only the server (service role) can read or
-- write. Pages show photos through short-lived signed links made by the server.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('listing-photos', 'listing-photos', false, 4194304, array['image/jpeg'])
on conflict (id) do nothing;
