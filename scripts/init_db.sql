-- Preis-Tracker: Supabase-Schema (M1)
--
-- Einmalig ausfuehren: Supabase-Projekt -> SQL Editor -> New query -> diese
-- Datei komplett einfuegen -> Run.
--
-- Vier Tabellen:
--   products      geteilte, serverweite Liste getrackter Produkte
--   scrape_runs   ein Eintrag pro Scraping-Lauf und Produkt (Statistiken)
--   offers        aktuell bekannte Angebote je Produkt (upsert auf product_id+link)
--   price_points  Preis-Verlauf, wird ab jetzt mitgeschrieben (fuer spaetere
--                 Preis-Historie/Allzeittief-Features, in v1 noch nicht genutzt)

create table products (
  id                bigint generated always as identity primary key,
  name              text not null,                      -- Anzeigename, z.B. "PS5 Slim"
  slug              text not null unique,                -- normalisierter Vergleichsschluessel
  guild_id          text,                                -- vorbereitet fuer Multi-Server, in v1 ungenutzt
  status            text not null default 'pending',     -- pending | ready | error
  queries           jsonb not null default '[]'::jsonb,  -- Suchbegriff-Varianten
  required_keywords jsonb not null default '[]'::jsonb,  -- muessen ALLE im Titel vorkommen
  exclude_keywords  jsonb not null default '[]'::jsonb,   -- Ausschluss-Begriffe (Zubehoer etc.)
  sources           jsonb not null default
                    '["kleinanzeigen","ebay","backmarket","refurbed"]'::jsonb,
  min_price         numeric not null default 0,
  max_price         numeric,                              -- optional manuelle Obergrenze; null = KI entscheidet
  active            boolean not null default true,
  created_by        text,
  created_by_name   text,
  created_at        timestamptz not null default now(),
  last_scraped_at   timestamptz,
  last_run_id       bigint,
  fail_streak       int not null default 0
);

create table scrape_runs (
  id                 bigint generated always as identity primary key,
  product_id         bigint not null references products(id) on delete cascade,
  started_at         timestamptz not null default now(),
  finished_at        timestamptz,
  status             text not null default 'running',    -- ok | no_results | error
  error              text,
  offers_found       int default 0,   -- roh, nach lokalen Filtern (accept())
  offers_kept        int default 0,   -- nach KI-Relevanzpruefung + Preisrahmen
  offers_new         int default 0,   -- Links, die vorher noch nie gesehen wurden
  price_min          numeric,
  price_p25          numeric,
  price_median       numeric,
  price_p75          numeric,
  price_max          numeric,
  ai_market_estimate numeric,          -- die eigene Marktpreis-Schaetzung der KI fuer diesen Lauf
  ai_market_note     text
);

create table offers (
  id            bigint generated always as identity primary key,
  product_id    bigint not null references products(id) on delete cascade,
  link          text not null,
  title         text not null,
  price         numeric not null,
  source        text not null,
  image         text,
  tier          text,
  tier_note     text,                 -- die KI-Begruendung ("begruendung")
  first_seen_at timestamptz not null default now(),
  last_seen_at  timestamptz not null default now(),
  last_run_id   bigint,
  unique (product_id, link)           -- Upsert-Schluessel
);
create index on offers (product_id, last_run_id);

create table price_points (
  id         bigint generated always as identity primary key,
  product_id bigint not null references products(id) on delete cascade,
  run_id     bigint,
  link       text not null,
  price      numeric not null,
  seen_at    timestamptz not null default now()
);
create index on price_points (product_id, seen_at);

-- Row Level Security an, aber OHNE Policies: nur der server-seitige
-- service_role-Key (der RLS umgeht) darf lesen/schreiben. Kein anonymer
-- Client bekommt jemals Zugriff.
alter table products     enable row level security;
alter table scrape_runs  enable row level security;
alter table offers       enable row level security;
alter table price_points enable row level security;
