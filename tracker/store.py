"""
Supabase/PostgREST-Client: die geteilte, serverweite Produkt-Liste + der
Angebots-Cache. Reine HTTPS+JSON-Aufrufe (requests) — kein DB-Treiber noetig,
funktioniert identisch aus einem GitHub-Actions-Runner und einer Vercel-Function.
"""
import os
from datetime import datetime, timezone

import requests

from tracker.models import ALL_SOURCES, Product, slugify


class DuplicateProductError(Exception):
    """Wird geworfen, wenn ein Produkt mit demselben Slug schon existiert."""
    def __init__(self, name):
        super().__init__(f"Produkt '{name}' wird schon getrackt.")
        self.name = name


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _row_to_product(row):
    max_price = row.get("max_price")
    return Product(
        name=row["name"],
        slug=row["slug"],
        queries=row.get("queries") or [row["name"]],
        required_keywords=row.get("required_keywords") or [],
        exclude_keywords=row.get("exclude_keywords") or [],
        sources=row.get("sources") or list(ALL_SOURCES),
        min_price=float(row.get("min_price") or 0),
        max_price=float(max_price) if max_price is not None else None,
        id=row.get("id"),
        status=row.get("status", "ready"),
        fail_streak=row.get("fail_streak", 0),
    )


class Store:
    def __init__(self, base_url=None, key=None, timeout=8.0):
        self.base_url = (base_url or os.getenv("SUPABASE_URL", "")).rstrip("/")
        self.key = key or os.getenv("SUPABASE_SERVICE_KEY", "")
        self.timeout = timeout

    def _request(self, method, path, *, params=None, json_body=None, prefer=None):
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        url = f"{self.base_url}/rest/v1/{path}"
        resp = requests.request(method, url, headers=headers, params=params, json=json_body, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json() if resp.content else None

    # -----------------------------------------------------------------
    # Produkte
    # -----------------------------------------------------------------
    def list_products(self, active_only=True):
        params = {"select": "*"}
        if active_only:
            params["active"] = "eq.true"
        rows = self._request("GET", "products", params=params) or []
        return [_row_to_product(r) for r in rows]

    def get_product(self, product_id):
        rows = self._request("GET", "products", params={"select": "*", "id": f"eq.{product_id}"}) or []
        return _row_to_product(rows[0]) if rows else None

    def find_product(self, name_or_slug):
        slug = slugify(name_or_slug)
        rows = self._request("GET", "products", params={"select": "*", "slug": f"eq.{slug}"}) or []
        return _row_to_product(rows[0]) if rows else None

    def search_products(self, partial, limit=25):
        """Fuer Discord-Autocomplete: Name+Slug aller Produkte, deren Name
        `partial` enthaelt (case-insensitive)."""
        params = {"select": "name,slug", "name": f"ilike.*{partial}*", "limit": limit}
        return self._request("GET", "products", params=params) or []

    def add_product(self, name, *, created_by=None, created_by_name=None, guild_id=None):
        body = {
            "name": name,
            "slug": slugify(name),
            "guild_id": guild_id,
            "created_by": created_by,
            "created_by_name": created_by_name,
        }
        try:
            rows = self._request("POST", "products", json_body=body, prefer="return=representation")
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 409:
                raise DuplicateProductError(name) from exc
            raise
        return _row_to_product(rows[0])

    def set_product_config(self, product_id, *, queries=None, required_keywords=None,
                            exclude_keywords=None, min_price=None, sources=None, status=None):
        body = {}
        if queries is not None:
            body["queries"] = queries
        if required_keywords is not None:
            body["required_keywords"] = required_keywords
        if exclude_keywords is not None:
            body["exclude_keywords"] = exclude_keywords
        if min_price is not None:
            body["min_price"] = min_price
        if sources is not None:
            body["sources"] = sources
        if status is not None:
            body["status"] = status
        if not body:
            return
        self._request("PATCH", "products", params={"id": f"eq.{product_id}"}, json_body=body)

    def deactivate_product(self, product_id):
        rows = self._request(
            "PATCH", "products",
            params={"id": f"eq.{product_id}"},
            json_body={"active": False},
            prefer="return=representation",
        )
        return bool(rows)

    def products_due(self, limit=12):
        """Aktive Produkte, die am laengsten nicht mehr gescraped wurden zuerst
        (Budgeted-Round-Robin in runner.py)."""
        params = {
            "select": "*",
            "active": "eq.true",
            "order": "last_scraped_at.asc.nullsfirst",
            "limit": limit,
        }
        rows = self._request("GET", "products", params=params) or []
        return [_row_to_product(r) for r in rows]

    def touch_product(self, product_id, *, run_id, ok):
        # Read-then-write, nicht atomar: zwei ueberlappende Aufrufe koennten
        # theoretisch denselben alten fail_streak lesen und ein Inkrement
        # verlieren. Die eigentliche Absicherung dagegen ist der
        # `concurrency:`-Block in .github/workflows/price_tracker.yml (der
        # verhindert ueberlappende Cron-Laeufe ueberhaupt) -- das hier bleibt
        # bewusst ein einfaches Read-PATCH, da fail_streak nur ein Zaehler
        # fuer Alarm-Schwellen ist, kein Wert mit Korrektheitsanspruch.
        body = {"last_scraped_at": _now_iso(), "last_run_id": run_id}
        if ok:
            body["fail_streak"] = 0
        else:
            current = self.get_product(product_id)
            body["fail_streak"] = (current.fail_streak if current else 0) + 1
        self._request("PATCH", "products", params={"id": f"eq.{product_id}"}, json_body=body)

    # -----------------------------------------------------------------
    # Scrape-Laeufe
    # -----------------------------------------------------------------
    def start_run(self, product_id):
        rows = self._request(
            "POST", "scrape_runs",
            json_body={"product_id": product_id},
            prefer="return=representation",
        )
        return rows[0]["id"]

    def finish_run(self, run_id, **stats):
        body = dict(stats)
        body["finished_at"] = _now_iso()
        self._request("PATCH", "scrape_runs", params={"id": f"eq.{run_id}"}, json_body=body)

    def last_run(self, product_id):
        params = {
            "select": "*",
            "product_id": f"eq.{product_id}",
            "order": "started_at.desc",
            "limit": 1,
        }
        rows = self._request("GET", "scrape_runs", params=params) or []
        return rows[0] if rows else None

    # -----------------------------------------------------------------
    # Angebote
    # -----------------------------------------------------------------
    def upsert_offers(self, product_id, run_id, offers):
        """Schreibt/aktualisiert Angebote (Upsert auf product_id+link) und
        gibt die resultierenden Zeilen zurueck (inkl. first_seen_at) — daran
        erkennt der Aufrufer, welche Angebote NEU sind (first_seen_at >=
        Start des aktuellen Laufs)."""
        if not offers:
            return []
        payload = [{
            "product_id": product_id,
            "link": o["link"],
            "title": o["title"],
            "price": o["price"],
            "source": o["source"],
            "image": o.get("image"),
            "tier": o.get("tier"),
            "tier_note": o.get("tier_note"),
            "last_seen_at": _now_iso(),
            "last_run_id": run_id,
        } for o in offers]
        rows = self._request(
            "POST", "offers",
            params={"on_conflict": "product_id,link"},
            json_body=payload,
            prefer="resolution=merge-duplicates,return=representation",
        )
        return rows or []

    def current_offers(self, product_id, limit=25):
        params = {
            "select": "*",
            "product_id": f"eq.{product_id}",
            "order": "price.asc",
            "limit": limit,
        }
        return self._request("GET", "offers", params=params) or []

    def record_price_points(self, product_id, run_id, offers):
        if not offers:
            return
        payload = [{
            "product_id": product_id,
            "run_id": run_id,
            "link": o["link"],
            "price": o["price"],
        } for o in offers]
        self._request("POST", "price_points", json_body=payload)
