-- Initial database schema for LinguaBloom

create table if not exists schema_migrations (
  version     text primary key,
  applied_at  timestamptz not null default now()
);

create table sessions (
  id                  uuid primary key default gen_random_uuid(),
  token_hash          text not null unique,
  nickname            text check (char_length(nickname) <= 20),
  avatar              text not null default 'sprout',
  level               smallint not null default 1 check (level between 1 and 3),
  learning_streak     smallint not null default 0,
  turns_since_checkin smallint not null default 0,
  turn_count          integer  not null default 0,
  pending_item_id     text,
  pending_attempts    smallint not null default 0,
  last_feeling        text,
  created_at          timestamptz not null default now(),
  last_active_at      timestamptz not null default now(),
  expires_at          timestamptz not null default now() + interval '30 days'
);

create table messages (
  id         bigint generated always as identity primary key,
  session_id uuid not null references sessions(id) on delete cascade,
  role       text not null check (role in ('child','bot')),
  content    text not null,
  mode       text check (mode in ('learning','conversation','engagement','support')),
  created_at timestamptz not null default now()
);
create index messages_session_idx on messages (session_id, id desc);

create table attempts (
  id         bigint generated always as identity primary key,
  session_id uuid not null references sessions(id) on delete cascade,
  item_id    text not null,
  level      smallint not null,
  skill_tag  text not null,
  attempt_no smallint not null,
  result     text not null check (result in ('correct','incorrect','unsure','skipped','revealed')),
  counted    boolean not null,               -- first attempt of an exposure
  created_at timestamptz not null default now()
);
create index attempts_session_idx on attempts (session_id, id desc);

create table level_events (
  id         bigint generated always as identity primary key,
  session_id uuid not null references sessions(id) on delete cascade,
  from_level smallint not null,
  to_level   smallint not null,
  created_at timestamptz not null default now()
);

alter table sessions     enable row level security;
alter table messages     enable row level security;
alter table attempts     enable row level security;
alter table level_events enable row level security;
-- No policies: only the backend's direct connection can access data.
