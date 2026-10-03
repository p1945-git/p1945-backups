-- PHASE 2. A login that can READ the e-commerce database and do nothing else.
-- Run once as the database owner, with the password supplied at run time (never saved in this file):
--     psql "<owner connection>" -v pw="'<new password>'" -f backup_ro.sql
-- ⚠️ Run it only after the other schemas are listed:  \dn   — add a USAGE/SELECT block per extra schema.
CREATE ROLE backup_ro LOGIN PASSWORD :pw;
GRANT CONNECT ON DATABASE p1945_ecomm TO backup_ro;
GRANT USAGE ON SCHEMA public TO backup_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO backup_ro;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO backup_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO backup_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON SEQUENCES TO backup_ro;
ALTER ROLE backup_ro SET default_transaction_read_only = on;
-- Check:  psql "<backup_ro connection>" -c "CREATE TABLE x(a int)"   <- must FAIL.
