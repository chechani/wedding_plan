"""
Single source of truth for every DocType this app needs.

Doctypes are declared here as plain data instead of hand-written per-doctype
JSON fixture files, and created/updated idempotently by install.py (called on
after_install / after_migrate). This is the mechanism that makes the app
"generalize for any wedding, not just Riya x Avish": adding a field or a new
operational doctype means editing this one file, not hand-crafting a JSON
file plus a controller stub plus an __init__.py for every entity.

Field dicts use the same keys Frappe's DocField uses (fieldname, fieldtype,
label, options, reqd, ...); anything omitted takes Frappe's normal default.

`wedding_scoped: True` means: this doctype gets a mandatory `wedding` Link
field (added automatically, don't declare it yourself) and is registered in
permissions.py's WEDDING_SCOPED_DOCTYPES so a user can only ever see rows for
weddings they belong to (see wedding_plan/permissions.py).
"""

MODULE = "Wedding Plan"

PLANNER_ROLE = "Wedding Planner"

STANDARD_PERMISSIONS = [
    {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "report": 1, "export": 1},
    {"role": PLANNER_ROLE, "read": 1, "write": 1, "create": 1, "delete": 1, "report": 1, "export": 1},
]

READONLY_ADDITION = [
    {"role": "All", "read": 0},
]


def _doc(name, fields, wedding_scoped=True, autoname="hash", istable=0, extra_permissions=None, title_field=None):
    return {
        "name": name,
        "module": MODULE,
        "autoname": autoname,
        "istable": istable,
        "wedding_scoped": wedding_scoped,
        "title_field": title_field,
        "fields": fields,
        "permissions": STANDARD_PERMISSIONS + (extra_permissions or []),
    }


DOCTYPES = [
    # -- Tenant -----------------------------------------------------------
    _doc(
        "Wedding",
        wedding_scoped=False,
        autoname="field:slug",
        title_field="couple_names",
        fields=[
            {"fieldname": "slug", "label": "Slug", "fieldtype": "Data", "reqd": 1, "unique": 1,
             "description": "URL-safe id used by the Next.js frontend, e.g. riya-avish-2025"},
            {"fieldname": "couple_names", "label": "Couple Names", "fieldtype": "Data", "reqd": 1},
            {"fieldname": "start_date", "label": "Start Date", "fieldtype": "Date", "reqd": 1},
            {"fieldname": "end_date", "label": "End Date", "fieldtype": "Date", "reqd": 1},
            {"fieldname": "venues_summary", "label": "Venues Summary", "fieldtype": "Small Text"},
            {"fieldname": "status", "label": "Status", "fieldtype": "Select",
             "options": "Draft\nActive\nArchived", "default": "Draft"},
        ],
    ),
    _doc(
        "Wedding Member",
        wedding_scoped=True,
        fields=[
            {"fieldname": "user", "label": "User", "fieldtype": "Link", "options": "User", "reqd": 1, "in_list_view": 1},
            {"fieldname": "role", "label": "Role", "fieldtype": "Select", "reqd": 1, "in_list_view": 1, "options": "\n".join([
                "Owner", "Event Director", "Venue Commander", "Accommodation", "Convoy Controller",
                "Catering Liaison", "Guest Relations", "Finance", "Family Readonly", "Shadow Readonly",
            ])},
            {"fieldname": "venue_scope", "label": "Venue Scope", "fieldtype": "Link", "options": "WD Venue",
             "description": "Optional: restrict a venue-level role (Venue Commander, Accommodation) to one venue"},
        ],
    ),

    # -- Master data --------------------------------------------------------
    _doc("WD Sub Group", fields=[
        {"fieldname": "sub_group_name", "label": "Sub Group Name", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
    ]),
    _doc("WD Venue", fields=[
        {"fieldname": "venue_name", "label": "Venue Name", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
        {"fieldname": "location", "label": "Location", "fieldtype": "Data"},
        {"fieldname": "rooms_total", "label": "Rooms Total", "fieldtype": "Int"},
        {"fieldname": "notes", "label": "Notes", "fieldtype": "Small Text"},
    ]),
    _doc("WD Room", fields=[
        {"fieldname": "venue", "label": "Venue", "fieldtype": "Link", "options": "WD Venue", "reqd": 1, "in_list_view": 1},
        {"fieldname": "room_no", "label": "Room No", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
        {"fieldname": "room_type", "label": "Type", "fieldtype": "Data"},
        {"fieldname": "block", "label": "Block", "fieldtype": "Data"},
    ]),
    _doc("WD Function", title_field="function_name", fields=[
        {"fieldname": "function_name", "label": "Function Name", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
        {"fieldname": "date", "label": "Date", "fieldtype": "Date", "in_list_view": 1},
        {"fieldname": "venue", "label": "Venue", "fieldtype": "Link", "options": "WD Venue"},
        {"fieldname": "notes", "label": "Notes", "fieldtype": "Small Text"},
    ]),

    # -- Run sheet ------------------------------------------------------------
    _doc("WD Run Sheet Item", fields=[
        {"fieldname": "function", "label": "Function", "fieldtype": "Link", "options": "WD Function"},
        {"fieldname": "date", "label": "Date", "fieldtype": "Date", "reqd": 1, "in_list_view": 1},
        {"fieldname": "time", "label": "Time", "fieldtype": "Data", "reqd": 1, "in_list_view": 1,
         "description": "Free text, e.g. 07:00 — matches the run sheet's own display, not a strict Time field"},
        {"fieldname": "title", "label": "What Happens", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
        {"fieldname": "venue", "label": "Venue", "fieldtype": "Link", "options": "WD Venue", "in_list_view": 1},
        {"fieldname": "owner_label", "label": "Owner", "fieldtype": "Data"},
        {"fieldname": "notes", "label": "What It Needs", "fieldtype": "Small Text"},
        {"fieldname": "is_fixed", "label": "Fixed (cannot move)", "fieldtype": "Check"},
        {"fieldname": "is_assumption", "label": "Assumption — needs confirming", "fieldtype": "Check"},
        {"fieldname": "sort_order", "label": "Sort Order", "fieldtype": "Int", "default": "0"},
    ]),

    # -- Guests -----------------------------------------------------------
    _doc("WD Guest Function", wedding_scoped=False, istable=1, fields=[
        {"fieldname": "wd_function", "label": "Function", "fieldtype": "Link", "options": "WD Function", "reqd": 1, "in_list_view": 1},
    ]),
    _doc("WD Guest", title_field="household_name", fields=[
        {"fieldname": "household_name", "label": "Household", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
        {"fieldname": "primary_phone", "label": "Primary Phone", "fieldtype": "Data", "in_list_view": 1},
        {"fieldname": "alternate_phone", "label": "Alternate Phone", "fieldtype": "Data"},
        {"fieldname": "address", "label": "Address", "fieldtype": "Small Text"},
        {"fieldname": "city", "label": "City", "fieldtype": "Data", "in_list_view": 1},
        {"fieldname": "category", "label": "Category", "fieldtype": "Select", "options": "Local\nOutstation", "default": "Local", "in_list_view": 1},
        {"fieldname": "sub_group", "label": "Sub Group", "fieldtype": "Link", "options": "WD Sub Group", "in_list_view": 1},
        {"fieldname": "pax", "label": "Pax", "fieldtype": "Int", "default": "1", "in_list_view": 1},
        {"fieldname": "kids", "label": "Kids", "fieldtype": "Int", "default": "0"},
        {"fieldname": "owner_in_family", "label": "Owner In Family", "fieldtype": "Data"},
        {"fieldname": "rsvp_status", "label": "RSVP", "fieldtype": "Select", "options": "Pending\nConfirmed\nDeclined", "default": "Pending", "in_list_view": 1},
        {"fieldname": "patrika_status", "label": "Patrika", "fieldtype": "Select",
         "options": "Not Printed\nPending\nHanded\nCouriered\nDigital Only", "default": "Pending", "in_list_view": 1},
        {"fieldname": "patrika_delivered_by", "label": "Patrika Delivered By", "fieldtype": "Data"},
        {"fieldname": "patrika_date", "label": "Patrika Date", "fieldtype": "Date"},
        {"fieldname": "patrika_acknowledged", "label": "Patrika Acknowledged", "fieldtype": "Check"},
        {"fieldname": "stay_required", "label": "Stay Required", "fieldtype": "Check", "in_list_view": 1},
        {"fieldname": "venue", "label": "Venue", "fieldtype": "Link", "options": "WD Venue"},
        {"fieldname": "rooms_needed", "label": "Rooms Needed", "fieldtype": "Int"},
        {"fieldname": "arrival_mode", "label": "Arrival Mode", "fieldtype": "Select", "options": "\nAir\nTrain\nBus\nRoad\nLocal"},
        {"fieldname": "arrival_detail", "label": "Arrival Detail", "fieldtype": "Data"},
        {"fieldname": "arrival_datetime", "label": "Arrival Datetime", "fieldtype": "Datetime"},
        {"fieldname": "pickup_required", "label": "Pickup Required", "fieldtype": "Check"},
        {"fieldname": "pickup_point", "label": "Pickup Point", "fieldtype": "Data"},
        {"fieldname": "departure_datetime", "label": "Departure Datetime", "fieldtype": "Datetime"},
        {"fieldname": "dietary", "label": "Dietary", "fieldtype": "Select",
         "options": "Standard\nJain\nVegan\nDiabetic\nOther", "default": "Standard"},
        {"fieldname": "special_needs", "label": "Special Needs", "fieldtype": "Small Text"},
        {"fieldname": "hamper_tier", "label": "Hamper Tier", "fieldtype": "Select",
         "options": "VIP\nPremium\nStandard\nKids\nNone", "default": "None"},
        {"fieldname": "vip_protocol", "label": "VIP Protocol", "fieldtype": "Check"},
        {"fieldname": "functions_invited", "label": "Invited To", "fieldtype": "Table MultiSelect", "options": "WD Guest Function"},
    ]),
    _doc("WD Room Allotment", fields=[
        {"fieldname": "room", "label": "Room", "fieldtype": "Link", "options": "WD Room", "reqd": 1, "in_list_view": 1},
        {"fieldname": "guest", "label": "Guest", "fieldtype": "Link", "options": "WD Guest", "reqd": 1, "in_list_view": 1},
        {"fieldname": "check_in", "label": "Check In", "fieldtype": "Datetime", "in_list_view": 1},
        {"fieldname": "check_out", "label": "Check Out", "fieldtype": "Datetime", "in_list_view": 1},
        {"fieldname": "keys_handed", "label": "Keys Handed", "fieldtype": "Check"},
        {"fieldname": "hamper_placed", "label": "Hamper Placed", "fieldtype": "Check"},
        {"fieldname": "luggage_delivered", "label": "Luggage Delivered", "fieldtype": "Check"},
    ]),

    # -- Teams & approvals --------------------------------------------------
    _doc("WD Team", fields=[
        {"fieldname": "team_key", "label": "Key", "fieldtype": "Data", "reqd": 1},
        {"fieldname": "team_name", "label": "Team Name", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
        {"fieldname": "role_label", "label": "Role", "fieldtype": "Data"},
        {"fieldname": "scope", "label": "Scope", "fieldtype": "Small Text"},
        {"fieldname": "member_a_name", "label": "Member A — Name & Number", "fieldtype": "Data"},
        {"fieldname": "member_a_contact", "label": "Member A Contact", "fieldtype": "Data"},
        {"fieldname": "member_b_label", "label": "Member B Label", "fieldtype": "Data", "default": "Shadow"},
        {"fieldname": "member_b_name", "label": "Member B — Name & Number", "fieldtype": "Data"},
        {"fieldname": "member_b_contact", "label": "Member B Contact", "fieldtype": "Data"},
    ]),
    _doc("WD Approval Matrix Entry", fields=[
        {"fieldname": "situation", "label": "Situation", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
        {"fieldname": "decider", "label": "Decides", "fieldtype": "Data", "in_list_view": 1},
        {"fieldname": "limit_text", "label": "Limit", "fieldtype": "Data"},
        {"fieldname": "escalate_to", "label": "Escalate To", "fieldtype": "Data"},
    ]),

    # -- Vendors & technical --------------------------------------------------
    _doc("WD Vendor", title_field="vendor_name", fields=[
        {"fieldname": "vendor_name", "label": "Vendor Name", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
        {"fieldname": "scope", "label": "Scope", "fieldtype": "Small Text"},
        {"fieldname": "where_needed", "label": "Where Needed", "fieldtype": "Data"},
        {"fieldname": "contact_name", "label": "Contact Name & Number", "fieldtype": "Data", "in_list_view": 1},
        {"fieldname": "contact_phone", "label": "Contact Phone", "fieldtype": "Data"},
        {"fieldname": "advance_amount", "label": "Advance", "fieldtype": "Currency"},
        {"fieldname": "vendor_type", "label": "Vendor Type", "fieldtype": "Data"},
    ]),
    _doc("WD Anchor Brief", fields=[
        {"fieldname": "function", "label": "Function", "fieldtype": "Link", "options": "WD Function", "in_list_view": 1},
        {"fieldname": "style_needed", "label": "Style Needed", "fieldtype": "Data"},
        {"fieldname": "brief", "label": "Brief", "fieldtype": "Small Text"},
    ]),
    _doc("WD Tech Requirement", fields=[
        {"fieldname": "function", "label": "Function", "fieldtype": "Link", "options": "WD Function", "in_list_view": 1},
        {"fieldname": "sound", "label": "Sound", "fieldtype": "Small Text"},
        {"fieldname": "led_visual", "label": "LED / Visual", "fieldtype": "Small Text"},
        {"fieldname": "pyro_sfx", "label": "Pyro & SFX", "fieldtype": "Small Text"},
        {"fieldname": "light", "label": "Light", "fieldtype": "Small Text"},
    ]),

    # -- Catering -----------------------------------------------------------
    _doc("WD Meal Session", fields=[
        {"fieldname": "date", "label": "Date", "fieldtype": "Date", "reqd": 1, "in_list_view": 1},
        {"fieldname": "session_name", "label": "Session", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
        {"fieldname": "time", "label": "Time", "fieldtype": "Data"},
        {"fieldname": "venue", "label": "Venue", "fieldtype": "Link", "options": "WD Venue", "in_list_view": 1},
        {"fieldname": "vendor", "label": "Caterer", "fieldtype": "Link", "options": "WD Vendor", "in_list_view": 1},
        {"fieldname": "who_eats", "label": "Who Eats", "fieldtype": "Data"},
        {"fieldname": "guaranteed_plates", "label": "Guaranteed Plates", "fieldtype": "Int", "default": "0", "in_list_view": 1},
        {"fieldname": "jain_plates", "label": "Jain Plates", "fieldtype": "Int", "default": "0"},
        {"fieldname": "staff_coupons", "label": "Staff Coupons", "fieldtype": "Int", "default": "0"},
        {"fieldname": "kids_plates", "label": "Kids Plates", "fieldtype": "Int", "default": "0"},
        {"fieldname": "served_plates", "label": "Served Plates", "fieldtype": "Int"},
        {"fieldname": "rate", "label": "Rate", "fieldtype": "Currency", "default": "0", "in_list_view": 1},
        {"fieldname": "signed_by_caterer", "label": "Signed By Caterer", "fieldtype": "Check"},
        {"fieldname": "signed_by_liaison", "label": "Signed By Liaison", "fieldtype": "Check"},
        {"fieldname": "signed_by_commander", "label": "Signed By Venue Commander", "fieldtype": "Check"},
        {"fieldname": "slip_photo", "label": "Slip Photo", "fieldtype": "Attach Image"},
        {"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "Planned\nLocked\nClosed", "default": "Planned"},
    ], extra_permissions=[{"role": "Wedding Planner", "read": 1}]),

    # -- Transport ------------------------------------------------------------
    _doc("WD Vehicle", fields=[
        {"fieldname": "vehicle_number", "label": "Number", "fieldtype": "Data", "in_list_view": 1},
        {"fieldname": "vehicle_type", "label": "Type", "fieldtype": "Data", "in_list_view": 1},
        {"fieldname": "capacity", "label": "Capacity", "fieldtype": "Int"},
        {"fieldname": "driver_name", "label": "Driver Name", "fieldtype": "Data", "in_list_view": 1},
        {"fieldname": "driver_phone", "label": "Driver Phone", "fieldtype": "Data"},
        {"fieldname": "vendor", "label": "Vendor", "fieldtype": "Link", "options": "WD Vendor"},
    ]),
    _doc("WD Convoy Leg", fields=[
        {"fieldname": "leg_no", "label": "Leg No", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
        {"fieldname": "date", "label": "Date", "fieldtype": "Date", "reqd": 1, "in_list_view": 1},
        {"fieldname": "from_venue", "label": "From", "fieldtype": "Link", "options": "WD Venue", "in_list_view": 1},
        {"fieldname": "to_venue", "label": "To", "fieldtype": "Link", "options": "WD Venue", "in_list_view": 1},
        {"fieldname": "must_arrive", "label": "Must Arrive", "fieldtype": "Data"},
        {"fieldname": "depart_by", "label": "Depart By", "fieldtype": "Data"},
        {"fieldname": "total_pax", "label": "Total Pax", "fieldtype": "Int"},
        {"fieldname": "status", "label": "Status", "fieldtype": "Select",
         "options": "Planned\nBoarding\nDeparted\nArrived", "default": "Planned", "in_list_view": 1},
        {"fieldname": "notes", "label": "Notes", "fieldtype": "Small Text"},
    ]),
    _doc("WD Pickup", fields=[
        {"fieldname": "guest", "label": "Guest", "fieldtype": "Link", "options": "WD Guest", "in_list_view": 1},
        {"fieldname": "mode", "label": "Mode", "fieldtype": "Select", "options": "\nAir\nTrain\nBus\nRoad\nLocal"},
        {"fieldname": "detail", "label": "Detail", "fieldtype": "Data"},
        {"fieldname": "eta", "label": "ETA", "fieldtype": "Datetime", "in_list_view": 1},
        {"fieldname": "point", "label": "Point", "fieldtype": "Data", "in_list_view": 1},
        {"fieldname": "vehicle", "label": "Vehicle", "fieldtype": "Link", "options": "WD Vehicle"},
        {"fieldname": "greeter_name", "label": "Greeter", "fieldtype": "Data"},
        {"fieldname": "status", "label": "Status", "fieldtype": "Select",
         "options": "Waiting\nArrived\nPicked\nDropped", "default": "Waiting", "in_list_view": 1},
    ]),

    # -- Logistics ------------------------------------------------------------
    _doc("WD Crate", fields=[
        {"fieldname": "crate_no", "label": "Crate No", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
        {"fieldname": "destination_venue", "label": "Destination Venue", "fieldtype": "Link", "options": "WD Venue", "in_list_view": 1},
        {"fieldname": "contents", "label": "Contents", "fieldtype": "Small Text"},
        {"fieldname": "packed_by", "label": "Packed By", "fieldtype": "Data"},
        {"fieldname": "dispatched", "label": "Dispatched", "fieldtype": "Check", "in_list_view": 1},
        {"fieldname": "received_by", "label": "Received By", "fieldtype": "Data"},
        {"fieldname": "returned", "label": "Returned", "fieldtype": "Check"},
    ]),
    _doc("WD Shagun Entry", fields=[
        {"fieldname": "guest", "label": "Guest", "fieldtype": "Link", "options": "WD Guest", "in_list_view": 1},
        {"fieldname": "function", "label": "Function", "fieldtype": "Link", "options": "WD Function"},
        {"fieldname": "amount_or_item", "label": "Amount / Item", "fieldtype": "Data", "in_list_view": 1},
        {"fieldname": "received_by", "label": "Received By", "fieldtype": "Data"},
        {"fieldname": "counter_shift", "label": "Counter / Shift", "fieldtype": "Data"},
    ], extra_permissions=[{"role": "Wedding Planner", "read": 1}]),

    # -- Risks & gaps -----------------------------------------------------
    _doc("WD Risk", fields=[
        {"fieldname": "title", "label": "Risk", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
        {"fieldname": "why", "label": "Why It Bites Here", "fieldtype": "Small Text"},
        {"fieldname": "mitigation", "label": "Mitigation", "fieldtype": "Small Text"},
        {"fieldname": "owner_label", "label": "Owner", "fieldtype": "Data", "in_list_view": 1},
        {"fieldname": "severity", "label": "Severity", "fieldtype": "Select", "options": "Low\nMedium\nHigh", "default": "Medium", "in_list_view": 1},
    ]),
    _doc("WD Gap Note", fields=[
        {"fieldname": "title", "label": "Gap", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
        {"fieldname": "note", "label": "Note", "fieldtype": "Small Text"},
        {"fieldname": "severity", "label": "Severity", "fieldtype": "Select", "options": "Low\nMedium\nHigh", "default": "Medium", "in_list_view": 1},
    ]),

    # -- Import audit trail -------------------------------------------------
    _doc("WD Import Job", fields=[
        {"fieldname": "file", "label": "File", "fieldtype": "Attach", "in_list_view": 1},
        {"fieldname": "status", "label": "Status", "fieldtype": "Select",
         "options": "Processing\nDone\nFailed", "default": "Processing", "in_list_view": 1},
        {"fieldname": "rows_total", "label": "Rows Total", "fieldtype": "Int", "default": "0"},
        {"fieldname": "rows_succeeded", "label": "Rows Succeeded", "fieldtype": "Int", "default": "0"},
        {"fieldname": "rows_failed", "label": "Rows Failed", "fieldtype": "Int", "default": "0"},
        {"fieldname": "error_log", "label": "Error Log (JSON)", "fieldtype": "Long Text"},
        {"fieldname": "created_by_user", "label": "Created By", "fieldtype": "Link", "options": "User"},
    ]),

    # -- WhatsApp (whatsform.in — one shared installation) -------------------
    _doc("WD WhatsApp Template", wedding_scoped=False, fields=[
        {"fieldname": "template_key", "label": "Key", "fieldtype": "Data", "reqd": 1, "unique": 1, "in_list_view": 1},
        {"fieldname": "body", "label": "Body", "fieldtype": "Small Text", "reqd": 1},
        {"fieldname": "variables", "label": "Variables (comma-separated)", "fieldtype": "Data"},
        {"fieldname": "approval_status", "label": "Approval Status", "fieldtype": "Select",
         "options": "Draft\nSubmitted\nApproved\nRejected", "default": "Draft", "in_list_view": 1},
    ], extra_permissions=[{"role": "Wedding Planner", "read": 1, "write": 0, "create": 0, "delete": 0}]),
    _doc("WD WhatsApp Message Log", fields=[
        {"fieldname": "direction", "label": "Direction", "fieldtype": "Select", "options": "Out\nIn", "reqd": 1, "in_list_view": 1},
        {"fieldname": "template_key", "label": "Template Key", "fieldtype": "Data"},
        {"fieldname": "to_phone", "label": "To", "fieldtype": "Data", "in_list_view": 1},
        {"fieldname": "from_phone", "label": "From", "fieldtype": "Data"},
        {"fieldname": "payload", "label": "Payload (JSON)", "fieldtype": "Long Text"},
        {"fieldname": "status", "label": "Status", "fieldtype": "Data", "default": "Queued", "in_list_view": 1},
        {"fieldname": "provider_message_id", "label": "Provider Message Id", "fieldtype": "Data"},
    ], extra_permissions=[{"role": "Wedding Planner", "write": 0, "create": 0, "delete": 0}]),
]


def get_wedding_scoped_doctypes():
    return [d["name"] for d in DOCTYPES if d.get("wedding_scoped")]
