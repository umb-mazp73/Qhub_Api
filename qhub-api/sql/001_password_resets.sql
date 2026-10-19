-- /home/miguelzambrano/projects/Qhub/qhub-api/sql/001_password_resets.sql
-- Aplicar MANUALMENTE en Supabase (SQL Editor). El proyecto NO versiona el esquema:
-- las tablas y los RPC (registrar_usuario / registrar_empresa) ya viven solo en Supabase.
-- Este archivo es documentación + script de aplicación manual; no lo ejecuta ningún test.
--
-- NOTA DE INTEGRIDAD REFERENCIAL (fix #6): account_id y propietario_id son referencias
-- LÓGICAS, NO llaves foráneas. No se declara FK porque la cuenta de login es polimórfica
-- (una empresa vive en control_empresas y un usuario en usuarios: no hay una sola tabla
-- destino a la cual apuntar una FK). account_id es la PK REAL de la fila de login
-- (control_empresas.id | usuarios.id) y es la clave de anclaje de todas las escrituras.
-- Las filas de esta tabla expiran por TTL (expira_en) o se consumen al usarse (usado_en);
-- no se borran por cascada porque no hay FK.

create table if not exists public.password_resets (
    id              uuid primary key default gen_random_uuid(),
    propietario_tipo propietario_tipo not null,   -- enum existente: 'empresa' | 'usuario'
    -- NOTA DE ENUM (fix #7): la app SIEMPRE escribe el .value del enum PropietarioTipo
    -- ('empresa' / 'usuario') y al leer reconstruye con PropietarioTipo(valor). El
    -- round-trip valor <-> PropietarioTipo queda cubierto por un test unitario
    -- (tests/test_password_reset.py). Ambas variantes de columna (enum o text+check de
    -- abajo) aceptan esos mismos valores.
    propietario_id  uuid not null,                 -- id "de dueño" (empresa_id | usuarios.id); diagnóstico/agrupación (referencia LÓGICA, sin FK)
    account_id      uuid not null,                 -- PK REAL de la fila de login: control_empresas.id | usuarios.id (referencia LÓGICA, sin FK)
    token_hash      text not null unique,          -- SHA-256 hex del token crudo; nunca se guarda el crudo
    email           text not null,                 -- email (normalizado) de la fila de login; informativo
    expira_en       timestamptz not null,
    usado_en        timestamptz,                   -- null = sin usar
    creada_en       timestamptz not null default now()
);

-- Variante de respaldo si el tipo enum 'propietario_tipo' no existiera en esta instancia:
-- propietario_tipo text not null check (propietario_tipo in ('empresa','usuario')),

create index if not exists password_resets_token_hash_idx on public.password_resets (token_hash);
create index if not exists password_resets_account_idx on public.password_resets (propietario_tipo, account_id);
