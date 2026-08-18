-- Back Market ist keine unterstuetzte Quelle mehr (siehe tracker/scrapers.py).
-- Einmalig zusaetzlich ausfuehren: Supabase -> SQL Editor -> New query ->
-- diese Datei einfuegen -> Run.
--
-- Rein kosmetisch/vorsorglich: Neue Produkte (per /track) sollen "backmarket"
-- nicht mehr als Default-Quelle bekommen. Bereits gespeicherte Produkte mit
-- "backmarket" in ihren sources sind bereits unschaedlich, weil der Scraper
-- diesen Schluessel jetzt einfach ignoriert -- kein Datenverlust, keine Eile.

alter table products
  alter column sources set default '["kleinanzeigen","ebay","refurbed"]'::jsonb;
