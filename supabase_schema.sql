-- Ejecutar en Supabase Dashboard > SQL Editor
create extension if not exists pgcrypto;

create table if not exists public.postulaciones (
  id uuid primary key default gen_random_uuid(),
  nombre text not null,
  discord_id text,
  discord_username text,
  rol text,
  rango text,
  region text,
  descripcion text,
  foto_url text,
  estado text not null default 'pendiente' check (estado in ('pendiente', 'aprobada', 'rechazada')),
  motivo_rechazo text,
  discord_webhook_id text,
  discord_postulacion_message_id text,
  discord_revision_message_id text,
  discord_aprobacion_message_id text,
  revisado_por_discord_id text,
  payload_original jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  reviewed_at timestamptz
);

create index if not exists postulaciones_estado_idx on public.postulaciones (estado);
create index if not exists postulaciones_discord_id_idx on public.postulaciones (discord_id);
create index if not exists postulaciones_created_at_idx on public.postulaciones (created_at desc);
-- Idempotencia: un mismo mensaje de Discord solo puede crear una postulación.
create unique index if not exists postulaciones_discord_message_unique_idx
  on public.postulaciones (discord_postulacion_message_id)
  where discord_postulacion_message_id is not null;

alter table public.postulaciones enable row level security;

-- El bot usa SUPABASE_SERVICE_ROLE_KEY en el servidor y no necesita una policy pública.
-- No expongas esa clave en el navegador ni la subas a GitHub/OneDrive compartido.
