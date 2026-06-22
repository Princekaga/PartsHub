"""Project / BOM (bill of materials) operations.

A "project" is a named bucket of parts (e.g. "Quadcopter v2"). Each item links a
product with a quantity. The BOM view groups items by vendor and computes subtotals
plus a grand total — this is what makes multi-vendor planning easy.
"""
from .database import db
from . import checkout


def list_projects() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT pr.*, COUNT(pi.id) AS item_count
            FROM projects pr
            LEFT JOIN project_items pi ON pi.project_id = pr.id
            GROUP BY pr.id
            ORDER BY pr.created_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def create_project(name: str) -> int:
    with db() as conn:
        cur = conn.execute("INSERT INTO projects (name) VALUES (?)", (name.strip() or "Untitled",))
        return cur.lastrowid


def delete_project(project_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))


def add_item(project_id: int, product_id: int, quantity: int = 1) -> None:
    """Add a product to a project, or bump its quantity if already present."""
    with db() as conn:
        conn.execute(
            """
            INSERT INTO project_items (project_id, product_id, quantity)
            VALUES (?, ?, ?)
            ON CONFLICT(project_id, product_id)
            DO UPDATE SET quantity = quantity + excluded.quantity
            """,
            (project_id, product_id, max(1, quantity)),
        )


def set_quantity(project_id: int, product_id: int, quantity: int) -> None:
    with db() as conn:
        if quantity <= 0:
            conn.execute(
                "DELETE FROM project_items WHERE project_id = ? AND product_id = ?",
                (project_id, product_id),
            )
        else:
            conn.execute(
                "UPDATE project_items SET quantity = ? WHERE project_id = ? AND product_id = ?",
                (quantity, project_id, product_id),
            )


def remove_item(project_id: int, product_id: int) -> None:
    with db() as conn:
        conn.execute(
            "DELETE FROM project_items WHERE project_id = ? AND product_id = ?",
            (project_id, product_id),
        )


def get_project(project_id: int) -> dict | None:
    """Return a project plus its items grouped by vendor, with totals."""
    with db() as conn:
        proj = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not proj:
            return None
        items = conn.execute(
            """
            SELECT pi.quantity, p.*
            FROM project_items pi
            JOIN products p ON p.id = pi.product_id
            WHERE pi.project_id = ?
            ORDER BY p.vendor_label, p.title
            """,
            (project_id,),
        ).fetchall()

    # Group items by vendor and compute subtotals.
    vendors: dict[str, dict] = {}
    grand_total = 0.0
    for row in items:
        r = dict(row)
        line_total = (r["price"] or 0) * r["quantity"]
        r["line_total"] = line_total
        grand_total += line_total
        key = r["vendor"]
        if key not in vendors:
            vendors[key] = {"name": key, "label": r["vendor_label"], "items": [], "subtotal": 0.0}
        vendors[key]["items"].append(r)
        vendors[key]["subtotal"] += line_total

    # Attach the sign-in link + pre-filled cart handoff for each vendor.
    for name, group in vendors.items():
        group["login_url"] = checkout.login_url(name)
        group["checkout"] = checkout.build_handoff(name, group["items"])

    return {
        "id": proj["id"],
        "name": proj["name"],
        "created_at": proj["created_at"],
        "vendors": list(vendors.values()),
        "grand_total": grand_total,
        "item_count": len(items),
    }
