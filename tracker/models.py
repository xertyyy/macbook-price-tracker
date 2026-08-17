"""
Datenmodelle. In M0 gibt es genau ein hartcodiertes Product-Literal (siehe
runner.py) — ab M1 kommen Product-Objekte aus der Supabase-Datenbank statt
aus dem Code, aber die Form bleibt dieselbe.
"""
import re
import unicodedata
from dataclasses import dataclass, field

# Alle vier aktuell unterstuetzten Marktplaetze — siehe tracker/scrapers.py.
ALL_SOURCES = ["kleinanzeigen", "ebay", "backmarket", "refurbed"]


def slugify(name):
    """Normalisiert einen Produktnamen zu einem eindeutigen Vergleichsschluessel,
    damit z. B. "PS5 Slim" und "ps5  slim " als dasselbe Produkt gelten."""
    normalized = unicodedata.normalize("NFKD", name)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")
    return slug


@dataclass
class Product:
    name: str
    slug: str = ""
    queries: list = field(default_factory=list)
    required_keywords: list = field(default_factory=list)
    exclude_keywords: list = field(default_factory=list)
    sources: list = field(default_factory=lambda: list(ALL_SOURCES))
    min_price: float = 0.0
    max_price: float = None

    def __post_init__(self):
        if not self.slug:
            self.slug = slugify(self.name)
        if not self.queries:
            self.queries = [self.name]
