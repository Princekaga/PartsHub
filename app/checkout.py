"""Per-vendor checkout handoffs: a sign-in link plus pre-filled cart deep links.

Privacy model: we never see or store the user's vendor credentials. The user signs
in on each vendor's OWN site (a normal new-tab login we don't touch); at checkout we
open that vendor with the cart pre-filled via a deep link, so the items land in their
already-logged-in cart and they just review and pay.

Deep-link formats by platform:
  Shopify     : <base>/cart/<variantId>:<qty>,<variantId>:<qty>   -> all items, one click
  WooCommerce : <base>/?add-to-cart=<productId>&quantity=<qty>     -> one click per item
  Other       : link to each product page (user adds manually)

The platform-specific id lives in each product's `cart_ref` (Shopify variant id or
Woo product id), captured during ingestion.
"""
from .config import VENDORS

_TYPE = {v["name"]: v["type"] for v in VENDORS}
_BASE = {v["name"]: v["base_url"].rstrip("/") for v in VENDORS}

# Sign-in page on each vendor's own site (we only open it; the login happens there).
_LOGIN_BY_TYPE = {
    "shopify": "/account/login",
    "woocommerce": "/my-account/",
    "auto": "/my-account/",      # the "auto" vendors here resolve to WooCommerce
}
_LOGIN_OVERRIDE = {
    "sunrom": "/login",
    "robu": "/login/",
}


def login_url(vendor_name: str) -> str:
    """The vendor's own sign-in page (opened in a new tab; we never see the login)."""
    base = _BASE.get(vendor_name, "")
    if not base:
        return ""
    path = _LOGIN_OVERRIDE.get(vendor_name) or _LOGIN_BY_TYPE.get(_TYPE.get(vendor_name), "")
    return base + path


def _qty(item) -> int:
    try:
        return max(1, int(item.get("quantity", 1)))
    except (ValueError, TypeError):
        return 1


def build_handoff(vendor_name: str, items: list[dict]) -> dict:
    """Build the checkout handoff for one vendor's items.

    `items` are product rows that include title, url, in_stock, cart_ref, quantity.
    Returns a dict consumed by the BOM template.
    """
    base = _BASE.get(vendor_name, "")
    typ = _TYPE.get(vendor_name)
    refs = [(it, str(it.get("cart_ref") or "")) for it in items]
    has_ref = any(r for _, r in refs)

    # --- Shopify: one permalink adds every item and opens the cart ---
    if typ == "shopify" and has_ref:
        parts = [f"{r}:{_qty(it)}" for it, r in refs if r]
        url = f"{base}/cart/{','.join(parts)}" if parts else base
        return {
            "mode": "all",
            "primary": {"label": f"Add all {len(parts)} item(s) & open cart", "url": url},
            "items": _page_links([it for it, r in refs if not r]),
            "note": "Opens your cart on the vendor site with everything pre-filled — just pay.",
        }

    # --- WooCommerce: one add-to-cart link per item ---
    if typ in ("woocommerce", "auto") and has_ref:
        links = []
        for it, r in refs:
            if r:
                links.append({
                    "title": it["title"], "qty": _qty(it), "in_stock": it.get("in_stock", 1),
                    "url": f"{base}/?add-to-cart={r}&quantity={_qty(it)}", "adds": True,
                })
            else:
                links.append({
                    "title": it["title"], "qty": _qty(it), "in_stock": it.get("in_stock", 1),
                    "url": it["url"], "adds": False,
                })
        return {
            "mode": "per_item",
            "primary": None,
            "items": links,
            "note": "Click each to add it straight to your cart on the vendor site.",
        }

    # --- Fallback (Sunrom, Ktron, Robu, or any item without a cart ref) ---
    return {
        "mode": "pages",
        "primary": None,
        "items": _page_links(items),
        "note": "Open each product page and add it to your cart on the vendor site.",
    }


def _page_links(items: list[dict]) -> list[dict]:
    return [{
        "title": it["title"], "qty": _qty(it), "in_stock": it.get("in_stock", 1),
        "url": it["url"], "adds": False,
    } for it in items]
