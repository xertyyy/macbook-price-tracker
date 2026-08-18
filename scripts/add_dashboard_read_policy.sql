-- Lese-Zugriff fuer das Dashboard (dashboard/index.html)
--
-- Einmalig zusaetzlich zu init_db.sql ausfuehren: Supabase -> SQL Editor ->
-- New query -> diese Datei einfuegen -> Run.
--
-- Erlaubt dem OEFFENTLICHEN (anon/publishable) Key NUR lesenden Zugriff
-- (SELECT) auf products und offers -- fuer das lokale Dashboard, das direkt
-- aus dem Browser gegen Supabase abfragt. Schreibzugriff (INSERT/UPDATE/
-- DELETE) bleibt weiterhin ausschliesslich dem geheimen service_role-Key
-- vorbehalten, da dafuer keine Policies existieren.

create policy "public read products" on products
  for select
  to anon
  using (true);

create policy "public read offers" on offers
  for select
  to anon
  using (true);
