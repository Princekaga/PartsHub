"""Ingestion runner: fetch every configured vendor and upsert into SQLite.

Run it via:  python -m scripts.ingest
or import and call ingest_all() from code / a scheduler.

Design notes:
- Upsert by (vendor, external_id) so re-running refreshes prices/stock instead of
  creating duplicates.
- Each vendor is wrapped in try/except so one failing store doesn't abort the run.
"""
from datetime import datetime

from ..config import VENDORS
from ..database import db, init_db, normalize_title
from . import shopify, woocommerce, auto, sunrom, robu

ADAPTERS = {
    "shopify": shopify.fetch_products,
    "woocommerce": woocommerce.fetch_products,
    "auto": auto.fetch_products,
    "sunrom": sunrom.fetch_products,
    "robu": robu.fetch_products,
}


def ingest_all(vendors: list[dict] | None = None) -> dict:
    """Fetch and store all vendors. Returns a per-vendor count summary."""
    init_db()
    vendors = vendors if vendors is not None else VENDORS
    summary: dict[str, int] = {}

    for vendor in vendors:
        adapter = ADAPTERS.get(vendor["type"])
        if not adapter:
            print(f"  [{vendor['name']}] no adapter for type '{vendor['type']}', skipping")
            continue

        print(f"Fetching {vendor['label']} ...")
        try:
            records = adapter(vendor)
        except Exception as exc:
            print(f"  [{vendor['name']}] ingestion error: {exc}")
            summary[vendor["name"]] = 0
            continue

        stored = _upsert(records)
        summary[vendor["name"]] = stored
        print(f"  [{vendor['name']}] stored/updated {stored} products")

    total = sum(summary.values())
    print(f"Done. {total} products across {len(summary)} vendors.")
    return summary


def _upsert(records: list[dict]) -> int:
    """Insert or update product rows. Returns how many were written."""
    now = datetime.utcnow().isoformat(timespec="seconds")
    count = 0
    with db() as conn:
        for r in records:
            if not r["title"]:
                continue
            conn.execute(
                """
                INSERT INTO products
                    (vendor, vendor_label, external_id, title, description, sku,
                     brand, category, price, compare_at_price, currency, in_stock,
                     url, image, cart_ref, norm_key, updated_at)
                VALUES
                    (:vendor, :vendor_label, :external_id, :title, :description, :sku,
                     :brand, :category, :price, :compare_at_price, :currency, :in_stock,
                     :url, :image, :cart_ref, :norm_key, :updated_at)
                ON CONFLICT(vendor, external_id) DO UPDATE SET
                    title=excluded.title,
                    description=excluded.description,
                    sku=excluded.sku,
                    brand=excluded.brand,
                    category=excluded.category,
                    price=excluded.price,
                    compare_at_price=excluded.compare_at_price,
                    in_stock=excluded.in_stock,
                    url=excluded.url,
                    image=excluded.image,
                    cart_ref=excluded.cart_ref,
                    norm_key=excluded.norm_key,
                    updated_at=excluded.updated_at
                """,
                {**r, "norm_key": normalize_title(r["title"]), "updated_at": now},
            )
            count += 1
    return count


if __name__ == "__main__":
    ingest_all()
