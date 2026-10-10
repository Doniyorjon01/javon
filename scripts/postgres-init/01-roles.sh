#!/usr/bin/env bash
# Runs once, by the postgres image, on an EMPTY data volume only.
# To re-run it locally: docker compose down -v (this deletes all local data).
#
#   postgres     superuser, for emergencies only
#   javon_owner  owns the database and every table; Alembic connects as it
#   javon_app    the API; no ownership, no BYPASSRLS -> RLS always applies
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
     -v owner_pw="$JAVON_OWNER_PASSWORD" \
     -v app_pw="$JAVON_APP_PASSWORD" <<'SQL'
CREATE ROLE javon_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'owner_pw';
CREATE ROLE javon_app   LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD :'app_pw';

CREATE DATABASE javon OWNER javon_owner;

\connect javon

ALTER SCHEMA public OWNER TO javon_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO javon_app;

-- Every table and sequence javon_owner creates later is usable by the API role.
ALTER DEFAULT PRIVILEGES FOR ROLE javon_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO javon_app;
ALTER DEFAULT PRIVILEGES FOR ROLE javon_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO javon_app;
SQL
