"""Shared scraper utilities and the normalized product shape.

Every adapter (Shopify, WooCommerce, ...) returns a list of dicts with EXACTLY the
keys defined in `normalized_product`. The ingestion runner then stores them, so the
rest of the app never needs to know which vendor a product came from.
"""
import re
import html as html_lib


def strip_html(text: str | None) -> str:
    """Turn an HTML description into plain text (cheap, dependency-free)."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)      # remove tags
    text = html_lib.unescape(text)            # &amp; -> &
    text = re.sub(r"\s+", " ", text).strip()  # collapse whitespace
    return text[:2000]                        # keep descriptions reasonable


def normalized_product(
    *,
    vendor: str,
    vendor_label: str,
    external_id: str,
    title: str,
    description: str = "",
    sku: str = "",
    brand: str = "",
    category: str = "",
    price: float | None = None,
    compare_at_price: float | None = None,
    currency: str = "INR",
    in_stock: bool = True,
    url: str = "",
    image: str = "",
    cart_ref: str = "",
) -> dict:
    """Build one normalized product record (the single shape used everywhere).

    cart_ref is the platform-specific id used to build a "pre-filled cart" deep link
    at checkout: the Shopify variant id (for /cart/<variant>:<qty>) or the WooCommerce
    product id (for ?add-to-cart=<id>). Empty when the vendor has no cart deep link.
    """
    return {
        "vendor": vendor,
        "vendor_label": vendor_label,
        "external_id": str(external_id),
        "title": (title or "").strip(),
        "description": strip_html(description),
        "sku": (sku or "").strip(),
        "brand": (brand or "").strip(),
        "category": (category or "").strip(),
        "price": price,
        "compare_at_price": compare_at_price,
        "currency": currency,
        "in_stock": 1 if in_stock else 0,
        "url": url,
        "image": image,
        "cart_ref": (str(cart_ref) if cart_ref else ""),
    }


def to_float(value) -> float | None:
    """Parse a price-like value into a float, or None."""
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return None
