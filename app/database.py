"""SQLite access layer.

We use the standard-library `sqlite3` module (no ORM) to keep things simple and
easy to learn. The database is a single file (see config.DB_PATH).

Key features used:
- FTS5 virtual table for fast full-text search over product titles.
- A normalized `norm_key` column to group "the same part" across vendors.
"""
import sqlite3
import re
from contextlib import contextmanager

from .config import DB_PATH


def get_connection() -> sqlite3.Connection:
    """Open a connection with sensible defaults (rows behave like dicts)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row          # access columns by name
    try:
        # WAL gives better concurrent reads, but some network/mounted filesystems
        # don't support it — fall back to the default journal mode if so.
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db():
    """Context manager that commits on success and always closes."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor           TEXT NOT NULL,
    vendor_label     TEXT NOT NULL,
    external_id      TEXT NOT NULL,
    title            TEXT NOT NULL,
    description      TEXT,
    sku              TEXT,
    brand            TEXT,
    category         TEXT,
    price            REAL,
    compare_at_price REAL,
    currency         TEXT DEFAULT 'INR',
    in_stock         INTEGER DEFAULT 1,
    url              TEXT,
    image            TEXT,
    cart_ref         TEXT,
    norm_key         TEXT,
    updated_at       TEXT,
    UNIQUE(vendor, external_id)
);

CREATE INDEX IF NOT EXISTS idx_products_norm_key ON products(norm_key);
CREATE INDEX IF NOT EXISTS idx_products_vendor   ON products(vendor);

-- Full-text search index. Content is kept in sync by the triggers below.
CREATE VIRTUAL TABLE IF NOT EXISTS products_fts USING fts5(
    title, brand, category, sku,
    content='products', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS products_ai AFTER INSERT ON products BEGIN
    INSERT INTO products_fts(rowid, title, brand, category, sku)
    VALUES (new.id, new.title, new.brand, new.category, new.sku);
END;
CREATE TRIGGER IF NOT EXISTS products_ad AFTER DELETE ON products BEGIN
    INSERT INTO products_fts(products_fts, rowid, title, brand, category, sku)
    VALUES ('delete', old.id, old.title, old.brand, old.category, old.sku);
END;
CREATE TRIGGER IF NOT EXISTS products_au AFTER UPDATE ON products BEGIN
    INSERT INTO products_fts(products_fts, rowid, title, brand, category, sku)
    VALUES ('delete', old.id, old.title, old.brand, old.category, old.sku);
    INSERT INTO products_fts(rowid, title, brand, category, sku)
    VALUES (new.id, new.title, new.brand, new.category, new.sku);
END;

CREATE TABLE IF NOT EXISTS projects (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS project_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    quantity   INTEGER NOT NULL DEFAULT 1,
    UNIQUE(project_id, product_id)
);
"""


def init_db() -> None:
    """Create tables/indexes/triggers if they don't exist yet."""
    with db() as conn:
        conn.executescript(SCHEMA)
        # Migrate databases created before the cart_ref column existed.
        cols = [r[1] for r in conn.execute("PRAGMA table_info(products)").fetchall()]
        if "cart_ref" not in cols:
            conn.execute("ALTER TABLE products ADD COLUMN cart_ref TEXT DEFAULT ''")


# A few common throwaway tokens that hurt grouping accuracy.
_STOPWORDS = {
    "the", "a", "an", "for", "with", "and", "of", "to", "pcs", "pcs.",
    "piece", "pieces", "set", "kit", "new", "original", "genuine",
}


def normalize_title(title: str) -> str:
    """Produce a comparison key from a product title.

    Lowercase, strip punctuation, drop stopwords, sort the remaining tokens.
    Two listings of the same part at different vendors should map to the same key
    even if word order or minor wording differs. This is intentionally simple --
    it powers grouping, and exact matches are double-checked by SKU elsewhere.
    """
    if not title:
        return ""
    text = title.lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)          # keep alphanumerics
    tokens = [t for t in text.split() if t and t not in _STOPWORDS]
    tokens = sorted(set(tokens))
    return " ".join(tokens)
