"""
Registry of which DocTypes are wedding-scoped.

DocType schemas themselves are plain Frappe JSON fixtures under
wedding_plan/wedding_plan/doctype/<doctype>/<doctype>.json (plus the usual
controller .py/.js/test_*.py) and are created/updated the normal Frappe way
by `bench migrate` — this file no longer generates them.

"Wedding-scoped" means: the doctype has a mandatory `wedding` Link field and
is registered in permissions.py's checks so a user can only ever see rows
for weddings they belong to (see wedding_plan/permissions.py). It's kept
here, separate from the JSON files, because permissions.py and hooks.py
both need this list and a JSON DocType schema has no field for "is this
tenant-scoped".
"""

PLANNER_ROLE = "Wedding Planner"

WEDDING_SCOPED_DOCTYPES = [
    "Wedding Member",
    "WD Sub Group",
    "WD Venue",
    "WD Room",
    "WD Function",
    "WD Run Sheet Item",
    "WD Guest",
    "WD Room Allotment",
    "WD Team",
    "WD Approval Matrix Entry",
    "WD Vendor",
    "WD Anchor Brief",
    "WD Tech Requirement",
    "WD Meal Session",
    "WD Vehicle",
    "WD Convoy Leg",
    "WD Pickup",
    "WD Crate",
    "WD Shagun Entry",
    "WD Risk",
    "WD Gap Note",
    "WD Import Job",
    "WD WhatsApp Message Log",
]


def get_wedding_scoped_doctypes():
    return list(WEDDING_SCOPED_DOCTYPES)
