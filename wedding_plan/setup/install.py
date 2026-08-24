"""
Runs on `bench install-app wedding_plan` (after_install) and again on every
`bench migrate` (after_migrate). DocType schemas live as native Frappe JSON
fixtures under wedding_plan/wedding_plan/doctype/ and are created/updated by
Frappe itself as part of migrate, so this module only creates the "Wedding
Planner" Role — a data record, not part of any DocType's schema, so it isn't
covered by that sync.
"""
import frappe

from wedding_plan.setup.doctype_specs import PLANNER_ROLE

# Standard invitation channels shown in the frontend's distribution matrix.
# channel_code must match the frontend's ChannelKey values exactly (see
# frontend/components/invitations/mockData.ts) since WD Invitation Channel
# autonames on channel_code and the frontend uses that code as a Link value
# with no translation layer.
STANDARD_INVITATION_CHANNELS = [
    {
        "channel_code": "ganesh",
        "channel_name": "Ganesh patrika",
        "short_label": "Ganesh",
        "sort_order": 1,
        "acknowledgement_required": 1,
        "delivery_tracking_required": 1,
        "description": "The first invitation — placed before the kuldevi or at the temple, and given to the eldest family member before general distribution.",
        "typical_owner": "Family elder, with pandit ji",
        "redo_policy": "Once only",
        "acknowledgement_expectation": "Ritual completed, photographed",
    },
    {
        "channel_code": "main",
        "channel_name": "Main patrika",
        "short_label": "Main",
        "sort_order": 2,
        "acknowledgement_required": 1,
        "delivery_tracking_required": 1,
        "description": "The printed wedding card. Hand delivered, couriered, sent via a relative, or collected.",
        "typical_owner": "Runners, family, courier",
        "redo_policy": "Once, redo if failed",
        "acknowledgement_expectation": "Met in person, signature, courier POD plus a confirming call",
    },
    {
        "channel_code": "manvaar",
        "channel_name": "Manvaar / manuhaar",
        "short_label": "Manvaar",
        "sort_order": 3,
        "acknowledgement_required": 1,
        "delivery_tracking_required": 0,
        "description": "The personal insistence — a visit or call after the card, usually by a senior, naming the specific functions they must attend. Often with a mithai or dry-fruit box.",
        "typical_owner": "Papa, Mummy, Rahul, senior relatives",
        "redo_policy": "Yes, often twice",
        "acknowledgement_expectation": "Spoke to the invitee directly, functions named",
    },
    {
        "channel_code": "phone",
        "channel_name": "Phone invitation",
        "short_label": "Phone",
        "sort_order": 4,
        "acknowledgement_required": 1,
        "delivery_tracking_required": 0,
        "description": "A call inviting them, logged with who called, when, and who they spoke to.",
        "typical_owner": "Household owner in the family",
        "redo_policy": "Yes",
        "acknowledgement_expectation": "Call connected and invitation extended",
    },
    {
        "channel_code": "visit",
        "channel_name": "Personal visit / nyota",
        "short_label": "Personal",
        "sort_order": 5,
        "acknowledgement_required": 1,
        "delivery_tracking_required": 1,
        "description": "Going to their home with the card and sweets. The highest-respect channel.",
        "typical_owner": "Family, never a runner",
        "redo_policy": "Yes",
        "acknowledgement_expectation": "Visit completed, who was met",
    },
    {
        "channel_code": "digital",
        "channel_name": "Digital patrika",
        "short_label": "Digital",
        "sort_order": 6,
        "acknowledgement_required": 1,
        "delivery_tracking_required": 0,
        "description": "WhatsApp e-card, video invite or link. Support, never the primary channel for elders.",
        "typical_owner": "Automated or guest relations",
        "redo_policy": "Yes",
        "acknowledgement_expectation": "WhatsApp delivered + read, or a reply",
    },
    {
        "channel_code": "samaj",
        "channel_name": "Samaj / community",
        "short_label": "Samaj",
        "sort_order": 7,
        "acknowledgement_required": 1,
        "delivery_tracking_required": 1,
        "description": "Jain Samaj — invitation to the samaj president and trustees, notice at the sthanak, community board announcement.",
        "typical_owner": "Dr. Vinod ji personally",
        "redo_policy": "Once",
        "acknowledgement_expectation": "Received by named office bearer",
    },
    {
        "channel_code": "office",
        "channel_name": "Office / business",
        "short_label": "Office",
        "sort_order": 8,
        "acknowledgement_required": 1,
        "delivery_tracking_required": 1,
        "description": "Delivered at the workplace to a firm rather than a home. Business friends and hospital associates.",
        "typical_owner": "Runner or staff",
        "redo_policy": "Once",
        "acknowledgement_expectation": "Received by name and designation at reception",
    },
    {
        "channel_code": "reminder",
        "channel_name": "T-7 reminder",
        "short_label": "T-7",
        "sort_order": 9,
        "acknowledgement_required": 1,
        "delivery_tracking_required": 0,
        "description": "The final call seven days out with timings, travel help and room details.",
        "typical_owner": "Guest relations + owner",
        "redo_policy": "Once",
        "acknowledgement_expectation": "Call connected, details given",
    },
]


def after_install():
    create_role()
    create_invitation_channels()
    frappe.db.commit()


def after_migrate():
    create_role()
    create_invitation_channels()


def create_role():
    if not frappe.db.exists("Role", PLANNER_ROLE):
        frappe.get_doc({
            "doctype": "Role",
            "role_name": PLANNER_ROLE,
            "desk_access": 1,
        }).insert(ignore_permissions=True)


def create_invitation_channels():
    """Idempotent: only inserts channels that don't exist yet by
    channel_code, never overwrites a channel a planner has since edited
    (e.g. disabled, re-labelled)."""
    for channel in STANDARD_INVITATION_CHANNELS:
        if frappe.db.exists("WD Invitation Channel", channel["channel_code"]):
            continue
        frappe.get_doc({"doctype": "WD Invitation Channel", **channel}).insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Convenience used by api.py when a brand-new wedding is created: makes the
# creating user a Wedding Member with role Owner and grants them the
# Wedding Planner role if they don't already have it.
# ---------------------------------------------------------------------------

def ensure_planner_role(user: str):
    user_doc = frappe.get_doc("User", user)
    if not any(r.role == PLANNER_ROLE for r in user_doc.roles):
        user_doc.append("roles", {"role": PLANNER_ROLE})
        user_doc.save(ignore_permissions=True)
