"""WooCommerce adapter.

Two ways to read a WooCommerce store:
  1. Store API (clean JSON):  /wp-json/wc/store/v1/products?per_page=100&page=N
  2. HTML scrape of the shop pages (fallback when the Store API is disabled).

Some stores disable the Store API and/or block non-browser User-Agents (FlyRobo
returns 403 to bot UAs). So we send a realistic browser User-Agent and fall back to
parsing the standard WooCommerce shop markup, which is largely theme-independent
(`li.product` cards with a title, price, image, and add-to-cart id).
"""
import re
import time
import html as html_lib
import httpx
from bs4 import BeautifulSoup

from ..config import REQUEST_TIMEOUT, REQUEST_DELAY, MAX_PAGES_PER_VENDOR
from .base import normalized_product, to_float, strip_html

# A realistic browser UA — many WooCommerce sites block unknown bot UAs (403).
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
PRICE_RE = re.compile(r"([\d,]+\.?\d*)")
PAGE_CAP = max(MAX_PAGES_PER_VENDOR, 120)


def fetch_products(vendor: dict) -> list[dict]:
    """Try the Store API first; if empty/disabled, fall back to HTML scraping."""
    records = _fetch_store_api(vendor)
    if records:
        return records
    print(f"  [{vendor['name']}] Store API unavailable — trying HTML shop pages…")
    return _fetch_html(vendor)


# ----------------------------------------------------------------- Store API

def _fetch_store_api(vendor: dict) -> list[dict]:
    base = vendor["base_url"].rstrip("/")
    headers = {"User-Agent": BROWSER_UA, "Accept": "application/json"}
    results: list[dict] = []
    seen: set = set()
    max_pages = PAGE_CAP
    with httpx.Client(timeout=REQUEST_TIMEOUT, headers=headers, follow_redirects=True) as client:
        for page in range(1, PAGE_CAP + 1):
            url = f"{base}/wp-json/wc/store/v1/products?per_page=100&page={page}"
            try:
                resp = client.get(url)
                if resp.status_code != 200:
                    break
                data = resp.json()
            except Exception as exc:
                print(f"  [{vendor['name']}] store API page {page} error: {exc}")
                break

            # On the first page, read WooCommerce's total-pages header so we know
            # exactly how far to paginate (prevents over-fetching past the catalog).
            if page == 1:
                tp = resp.headers.get("X-WP-TotalPages") or resp.headers.get("x-wp-totalpages")
                if tp and str(tp).isdigit() and int(tp) > 0:
                    max_pages = min(PAGE_CAP, int(tp))

            if not data:
                break

            new_count = 0
            for p in data:
                rec = _normalize_store_api(vendor, p)
                if not rec:
                    continue
                eid = rec["external_id"]
                if eid in seen:
                    continue
                seen.add(eid)
                results.append(rec)
                new_count += 1

            # Progress line so a long crawl never looks frozen.
            print(f"    [{vendor['name']}] store API page {page}/{max_pages} "
                  f"(+{new_count}, total {len(results)})")

            if new_count == 0:        # nothing new -> reached the end / repeating
                break
            if len(data) < 100:       # short page -> last page
                break
            if page >= max_pages:     # header-reported end
                break
            time.sleep(REQUEST_DELAY)
    return results


def _normalize_store_api(vendor: dict, p: dict) -> dict | None:
    prices = p.get("prices") or {}
    minor = prices.get("price")
    divisor = 10 ** int(prices.get("currency_minor_unit", 2) or 2)
    price = to_float(minor) / divisor if minor not in (None, "") else None
    images = p.get("images") or []
    return normalized_product(
        vendor=vendor["name"],
        vendor_label=vendor["label"],
        external_id=p.get("id"),
        title=html_lib.unescape(p.get("name", "")),
        description=strip_html(p.get("short_description") or p.get("description")),
        sku=p.get("sku", ""),
        brand="",
        category=", ".join(
            html_lib.unescape(c.get("name", "")) for c in (p.get("categories") or [])
        ),
        price=price,
        compare_at_price=None,
        currency=vendor.get("currency", "INR"),
        in_stock=bool(p.get("is_in_stock", True)),
        url=p.get("permalink", vendor["base_url"]),
        image=images[0]["src"] if images else "",
        cart_ref=str(p.get("id") or ""),   # Woo product id -> ?add-to-cart=<id>
    )


# ----------------------------------------------------------------- HTML fallback

def _fetch_html(vendor: dict) -> list[dict]:
    """Scrape the standard WooCommerce /shop/ listing pages.

    Works across most WooCommerce themes because it targets the conventional
    `li.product` card markup. Paginates via /shop/page/N/ until a page has no
    new products (or 404s).
    """
    base = vendor["base_url"].rstrip("/")
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    results: list[dict] = []
    seen: set[str] = set()

    with httpx.Client(timeout=REQUEST_TIMEOUT, headers=headers, follow_redirects=True) as client:
        for page in range(1, PAGE_CAP + 1):
            url = f"{base}/shop/" if page == 1 else f"{base}/shop/page/{page}/"
            try:
                resp = client.get(url)
            except Exception as exc:
                print(f"  [{vendor['name']}] shop page {page} failed: {exc}")
                break
            if resp.status_code != 200:
                break

            cards = parse_woo_listing(resp.text, base, vendor)
            new = [c for c in cards if c["external_id"] not in seen]
            if not new:
                break
            for c in new:
                seen.add(c["external_id"])
                results.append(c)
            print(f"    [{vendor['name']}] shop page {page} (+{len(new)}, total {len(results)})")
            time.sleep(REQUEST_DELAY)

    if not results:
        print(f"  [{vendor['name']}] no products found on /shop/ — the store may use a "
              f"different layout. Run: python scripts/check_vendor.py {base}")
    return results


def _abs_url(base: str, src: str) -> str:
    if not src:
        return ""
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return base + src
    return src


def _best_image(img) -> str:
    """Pick a real image URL, skipping lazy-load placeholders."""
    if img is None:
        return ""
    for attr in ("data-src", "data-lazy-src", "src"):
        val = img.get(attr, "")
        if val and "lazy" not in val and not val.endswith(".svg"):
            return val
    # Fall back to the first URL in a srcset.
    for attr in ("data-srcset", "srcset"):
        val = img.get(attr, "")
        if val:
            return val.split(",")[0].strip().split(" ")[0]
    return img.get("src", "")


def parse_woo_listing(html: str, base: str, vendor: dict) -> list[dict]:
    """Parse a WooCommerce shop page's product cards into normalized dicts."""
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("li.product, .product-grid-item, ul.products > li")

    out: list[dict] = []
    for li in cards:
        link = (li.select_one("a.woocommerce-LoopProduct-link")
                or li.select_one("a[href*='/product/']")
                or li.find("a", href=True))
        if not link or not link.get("href"):
            continue
        href = link["href"]

        title_el = li.select_one(
            ".woocommerce-loop-product__title, .wd-entities-title, h2, h3"
        )
        img = li.find("img")
        title = title_el.get_text(strip=True) if title_el else ""
        if not title and img is not None:
            title = (img.get("alt") or "").strip()
        if not title:
            title = href.rstrip("/").split("/")[-1].replace("-", " ").title()

        # Price: prefer the active/sale amount over the struck-through original.
        price = None
        price_box = li.select_one(".price")
        if price_box is not None:
            amt = (price_box.select_one("ins .amount")
                   or price_box.select_one(".amount")
                   or price_box)
            m = PRICE_RE.search(amt.get_text(" ", strip=True))
            if m:
                price = to_float(m.group(1))

        # Stable id: the add-to-cart product id, else the URL slug.
        # cart_id (numeric) also powers the ?add-to-cart=<id> checkout deep link.
        cart_id = ""
        atc = li.select_one("a[href*='add-to-cart=']")
        if atc:
            m = re.search(r"add-to-cart=(\d+)", atc["href"])
            if m:
                cart_id = m.group(1)
        ext = cart_id or href.rstrip("/").split("/")[-1]

        classes = " ".join(li.get("class", []))
        in_stock = "outofstock" not in classes

        out.append(normalized_product(
            vendor=vendor["name"],
            vendor_label=vendor["label"],
            external_id=ext,
            title=html_lib.unescape(title),
            sku="",
            brand="",
            category="",
            price=price,
            currency=vendor.get("currency", "INR"),
            in_stock=in_stock,
            url=_abs_url(base, href),
            image=_abs_url(base, _best_image(img)),
            cart_ref=cart_id,   # numeric product id for ?add-to-cart=, else "" -> product page
        ))
    return out
