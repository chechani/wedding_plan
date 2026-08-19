"""
Tenant isolation: a user may only see/act on rows belonging to weddings they
are a `Wedding Member` of. This is deliberately NOT done with Frappe's stock
User Permission mechanism, because that mechanism can't express "this user
holds a different role on Wedding A than on Wedding B" — and a wedding
planner who runs several weddings for different clients needs exactly that.
Instead:

  - Every wedding-scoped DocType gets read/write DocType-level permission
    granted to the single "Wedding Planner" Role (see doctype_specs.py).
  - This module's has_permission()/query condition functions then narrow
    that down per row, per user, based on the caller's `Wedding Member.role`
    for that row's wedding — see ROLE_WRITE_REQUIREMENTS below for the
    handful of doctypes where only specific roles may write.

Registered from hooks.py for every doctype in get_wedding_scoped_doctypes().
"""
import frappe

from wedding_plan.setup.doctype_specs import get_wedding_scoped_doctypes

READONLY_ROLES = {"Family Readonly", "Shadow Readonly"}

# Doctypes where write access is further restricted to specific Wedding
# Member roles (Owner/Event Director can always write; not listed = any
# non-readonly member can write). Mirrors erpnext-whatsapp-plan.md's B5
# roles-and-permissions table.
ROLE_WRITE_REQUIREMENTS = {
    "WD Meal Session": {"Catering Liaison", "Venue Commander"},
    "WD Convoy Leg": {"Convoy Controller"},
    "WD Pickup": {"Convoy Controller"},
    "WD Vehicle": {"Convoy Controller"},
    "WD Room Allotment": {"Accommodation"},
    "WD Vendor": {"Finance"},
}

ALWAYS_CAN_WRITE = {"Owner", "Event Director"}


def _member_weddings(user):
    return set(frappe.get_all("Wedding Member", filters={"user": user}, pluck="wedding"))


def _member_role(user, wedding):
    return frappe.db.get_value("Wedding Member", {"user": user, "wedding": wedding}, "role")


def _can_write_doctype(doctype, role):
    if role in ALWAYS_CAN_WRITE:
        return True
    if role in READONLY_ROLES:
        return False
    required = ROLE_WRITE_REQUIREMENTS.get(doctype)
    if not required:
        return True
    return role in required


def _wedding_query_condition(doctype):
    def condition(user=None):
        user = user or frappe.session.user
        if user == "Administrator" or "System Manager" in frappe.get_roles(user):
            return ""
        weddings = _member_weddings(user)
        if not weddings:
            return "1=0"
        escaped = ", ".join(frappe.db.escape(w) for w in weddings)
        return f"`tab{doctype}`.wedding in ({escaped})"

    return condition


def _wedding_has_permission(doctype):
    # Frappe's permission machinery calls has_permission hooks as
    # frappe.call(fn, doc=doc, ptype=ptype, user=user) — the keyword is
    # `ptype`, not `permission_type`. frappe.call silently drops kwargs a
    # function doesn't declare, so naming this wrong doesn't raise an error;
    # it just means the ptype value never arrives and every check falls
    # through as if it were a read. Keep the parameter name `ptype`.
    def check(doc, ptype=None, user=None):
        user = user or frappe.session.user
        if user == "Administrator" or "System Manager" in frappe.get_roles(user):
            return True
        wedding = getattr(doc, "wedding", None)
        if not wedding:
            return False
        role = _member_role(user, wedding)
        if not role:
            return False
        if ptype in ("write", "create", "delete", "submit", "cancel"):
            return _can_write_doctype(doctype, role)
        return True

    return check


def _wedding_doc_has_permission(doc, ptype=None, user=None):
    """has_permission for the Wedding doctype itself (keyed by doc.name, not doc.wedding)."""
    user = user or frappe.session.user
    if user == "Administrator" or "System Manager" in frappe.get_roles(user):
        return True
    role = _member_role(user, doc.name)
    if not role:
        return False
    if ptype in ("write", "create", "delete"):
        return role in ALWAYS_CAN_WRITE
    return True


def _wedding_doc_query_condition(user=None):
    user = user or frappe.session.user
    if user == "Administrator" or "System Manager" in frappe.get_roles(user):
        return ""
    weddings = _member_weddings(user)
    if not weddings:
        return "1=0"
    escaped = ", ".join(frappe.db.escape(w) for w in weddings)
    return f"`tabWedding`.name in ({escaped})"


# ---------------------------------------------------------------------------
# Module-level named functions, one per doctype, so hooks.py can reference
# each as a plain dotted string (frappe.get_attr needs a real module
# attribute — it can't resolve a closure returned at import time).
# ---------------------------------------------------------------------------

for _dt in get_wedding_scoped_doctypes():
    _suffix = frappe.scrub(_dt)
    globals()[f"query_conditions__{_suffix}"] = _wedding_query_condition(_dt)
    globals()[f"has_permission__{_suffix}"] = _wedding_has_permission(_dt)

query_conditions__wedding = _wedding_doc_query_condition
has_permission__wedding = _wedding_doc_has_permission
