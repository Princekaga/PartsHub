"""Shopify adapter.

Shopify stores expose a public, paginated JSON catalog at:
    https://<store>/products.json?limit=250&page=<n>

This is structured data (no HTML parsing needed) and is the most reliable source.
One adapter works for ANY Shopify store — Robocraze, ThinkRobotics, QuartzComponents
were all verified to use this format.

Each product can have several "variants" (e.g. sizes). For an MVP we take the first
variant as the representative price/SKU/stock; extending to all variants is easy.
"""
import time
import httpx

from ..config import USER_AGENT, REQUEST_TIMEOUT, REQUEST_DELAY, MAX_PAGES_PER_VENDOR
from .base import normalized_product, to_float


def fetch_products(vendor: dict) -> list[dict]:
    """Fetch and normalize all products for one Shopify vendor."""
    base = vendor["base_url"].rstrip("/")
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    results: list[dict] = []

    with httpx.Client(timeout=REQUEST_TIMEOUT, headers=headers, follow_redirects=True) as client:
        for page in range(1, MAX_PAGES_PER_VENDOR + 1):
            url = f"{base}/products.json?limit=250&page={page}"
            try:
                resp = client.get(url)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:  # network error, bad JSON, etc.
                print(f"  [{vendor['name']}] page {page} failed: {exc}")
                break

            products = data.get("products", [])
            if not products:
                break  # no more pages

            for p in products:
                record = _normalize_one(vendor, base, p)
                if record:
                    results.append(record)

            time.sleep(REQUEST_DELAY)  # be polite between pages

    return results


def _normalize_one(vendor: dict, base: str, p: dict) -> dict | None:
    """Convert one raw Shopify product into our normalized shape."""
    variants = p.get("variants") or []
    if not variants:
        return None
    v = variants[0]  # representative variant

    handle = p.get("handle", "")
    images = p.get("images") or []
    image = images[0]["src"] if images else ""

    # A product is "in stock" if any variant is available.
    in_stock = any(var.get("available") for var in variants)

    return normalized_product(
        vendor=vendor["name"],
        vendor_label=vendor["label"],
        external_id=p.get("id"),
        title=p.get("title", ""),
        description=p.get("body_html", ""),
        sku=v.get("sku", ""),
        brand=p.get("vendor", ""),          # Shopify "vendor" = manufacturer/brand
        category=p.get("product_type", ""),
        price=to_float(v.get("price")),
        compare_at_price=to_float(v.get("compare_at_price")),
        currency=vendor.get("currency", "INR"),
        in_stock=in_stock,
        url=f"{base}/products/{handle}" if handle else base,
        image=image,
        cart_ref=str(v.get("id") or ""),   # Shopify variant id -> /cart/<variant>:<qty>
    )
