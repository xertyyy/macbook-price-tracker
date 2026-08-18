-- Lese-Zugriff fuer das Dashboard (dashboard/index.html)
--
-- Einmalig zusaetzlich zu init_db.sql ausfuehren: Supabase -> SQL Editor ->
-- New query -> diese Datei einfuegen -> Run.
--
-- Erlaubt JEDEM Leser (oeffentlich, ueber den Publishable Key) NUR lesenden
-- Zugriff (SELECT) auf products und offers -- fuer das Dashboard, das direkt
-- aus dem Browser gegen Supabase abfragt. Schreibzugriff (INSERT/UPDATE/
-- DELETE) bleibt weiterhin ausschliesslich dem geheimen Secret-Key
-- vorbehalten, da dafuer keine Policies existieren.
--
-- Hinweis: "to public" statt "to anon" -- Supabases neues Key-System
-- (sb_publishable_/sb_secret_) mappt Anfragen nicht mehr auf die klassische
-- "anon"-Postgres-Rolle, daher greifen "to anon"-Policies damit nicht.
-- "to public" gilt unabhaengig von der Rolle und funktioniert zuverlaessig.

drop policy if exists "public read products" on products;
drop policy if exists "public read offers" on offers;

create policy "public read products" on products
  for select
  to public
  using (true);

create policy "public read offers" on offers
  for select
  to public
  using (true);
