-- RELOOP AI: knowledge base for the RAG disposal assistant (Phase 4).
-- Run once in Supabase: Dashboard -> SQL Editor -> paste -> Run.
-- Only the server (service-role key) can read or write these tables.

create extension if not exists vector;

create table if not exists public.knowledge_documents (
  id              uuid primary key default gen_random_uuid(),
  file_name       text not null,
  title           text not null,
  publisher       text,
  source_url      text,
  published_on    text,
  jurisdiction    text,
  content_sha256  text not null unique,
  chunk_count     integer not null default 0,
  status          text not null default 'active' check (status in ('active', 'archived')),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table if not exists public.knowledge_chunks (
  id           uuid primary key default gen_random_uuid(),
  document_id  uuid not null references public.knowledge_documents(id) on delete cascade,
  chunk_index  integer not null,
  content      text not null,
  heading      text,
  page_from    integer,
  embedding    vector(1024) not null,   -- voyage-4 at output_dimension 1024
  created_at   timestamptz not null default now(),
  unique (document_id, chunk_index)
);

create index if not exists knowledge_chunks_document_idx on public.knowledge_chunks (document_id);
create index if not exists knowledge_chunks_embedding_idx
  on public.knowledge_chunks using hnsw (embedding vector_cosine_ops);

-- keep updated_at fresh
create or replace function public.touch_updated_at() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.updated_at = now();
  return new;
end $$;

drop trigger if exists knowledge_documents_touch on public.knowledge_documents;
create trigger knowledge_documents_touch before update on public.knowledge_documents
  for each row execute function public.touch_updated_at();

-- Row-level security: enabled with no policies, so anon/authenticated clients get nothing.
-- The service role bypasses RLS and is used only on the server.
alter table public.knowledge_documents enable row level security;
alter table public.knowledge_chunks enable row level security;

-- Similarity search used by the assistant.
create or replace function public.match_knowledge_chunks(
  query_embedding vector(1024),
  match_count     integer default 6,
  min_similarity  double precision default 0.35
)
returns table (
  content      text,
  similarity   double precision,
  title        text,
  publisher    text,
  source_url   text,
  published_on text,
  heading      text,
  page_from    integer,
  chunk_index  integer
)
language sql stable
set search_path = public, extensions
as $$
  select c.content,
         1 - (c.embedding <=> query_embedding) as similarity,
         d.title, d.publisher, d.source_url, d.published_on,
         c.heading, c.page_from, c.chunk_index
  from public.knowledge_chunks c
  join public.knowledge_documents d on d.id = c.document_id
  where d.status = 'active'
    and 1 - (c.embedding <=> query_embedding) >= min_similarity
  order by c.embedding <=> query_embedding
  limit least(greatest(match_count, 1), 20);
$$;

revoke all on function public.match_knowledge_chunks(vector, integer, double precision) from public, anon, authenticated;
grant execute on function public.match_knowledge_chunks(vector, integer, double precision) to service_role;
