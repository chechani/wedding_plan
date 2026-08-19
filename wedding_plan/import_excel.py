"""
Multi-sheet Excel import — the mechanism that makes "define everything as a
new marriage" real (see erpnext-whatsapp-plan.md section B6, which this
follows: master data first, batches traceable, reconcile before you rely on
the numbers). One workbook, one sheet per doctype, sheets processed in
dependency order so a typo in a later sheet never corrupts an earlier one.

Each SHEETS entry describes:
  doctype       - the DocType to upsert into
  sheet_name    - the .xlsx sheet tab name (also the row 1 header row is
                   read literally as fieldnames, so a downloadable template
                   generated from this same table always matches)
  natural_key   - fieldnames that together identify "the same row" across
                   repeated imports (upsert key)
  links         - {fieldname: (link_doctype, lookup_fieldname)} — the sheet
                   holds a human-readable value (e.g. a venue name); this
                   resolves it to the linked doc's name *within this
                   wedding*, and is a row-level error if not found (matching
                   B6's "imports fail on missing links" — deliberately not
                   auto-created, so a typo in a venue name is caught here
                   instead of silently spawning a duplicate venue).
  multiselects  - {fieldname: (link_doctype, lookup_fieldname)} for
                   comma-separated text columns that map onto a Table
                   MultiSelect field (e.g. Guests' "Invited To" column).
"""
import json

import frappe
from openpyxl import Workbook, load_workbook

SHEETS = [
    {"doctype": "WD Sub Group", "sheet_name": "SubGroups", "natural_key": ["sub_group_name"]},
    {"doctype": "WD Venue", "sheet_name": "Venues", "natural_key": ["venue_name"]},
    {"doctype": "WD Function", "sheet_name": "Functions", "natural_key": ["function_name"],
     "links": {"venue": ("WD Venue", "venue_name")}},
    {"doctype": "WD Room", "sheet_name": "Rooms", "natural_key": ["venue", "room_no"],
     "links": {"venue": ("WD Venue", "venue_name")}},
    {"doctype": "WD Team", "sheet_name": "Teams", "natural_key": ["team_key"]},
    {"doctype": "WD Vendor", "sheet_name": "Vendors", "natural_key": ["vendor_name"]},
    {"doctype": "WD Guest", "sheet_name": "Guests", "natural_key": ["household_name", "primary_phone"],
     "links": {"sub_group": ("WD Sub Group", "sub_group_name"), "venue": ("WD Venue", "venue_name")},
     "multiselects": {"functions_invited": ("WD Function", "function_name")}},
    {"doctype": "WD Room Allotment", "sheet_name": "RoomAllotments", "natural_key": ["room", "guest"],
     "links": {"room": ("WD Room", "room_no"), "guest": ("WD Guest", "household_name")}},
    {"doctype": "WD Run Sheet Item", "sheet_name": "RunSheet", "natural_key": ["date", "time", "title"],
     "links": {"function": ("WD Function", "function_name"), "venue": ("WD Venue", "venue_name")}},
    {"doctype": "WD Anchor Brief", "sheet_name": "AnchorBriefs", "natural_key": ["function"],
     "links": {"function": ("WD Function", "function_name")}},
    {"doctype": "WD Tech Requirement", "sheet_name": "TechRequirements", "natural_key": ["function"],
     "links": {"function": ("WD Function", "function_name")}},
    {"doctype": "WD Meal Session", "sheet_name": "MealSessions", "natural_key": ["date", "session_name", "venue"],
     "links": {"venue": ("WD Venue", "venue_name"), "vendor": ("WD Vendor", "vendor_name")}},
    {"doctype": "WD Vehicle", "sheet_name": "Vehicles", "natural_key": ["vehicle_number"],
     "links": {"vendor": ("WD Vendor", "vendor_name")}},
    {"doctype": "WD Convoy Leg", "sheet_name": "ConvoyLegs", "natural_key": ["leg_no", "date"],
     "links": {"from_venue": ("WD Venue", "venue_name"), "to_venue": ("WD Venue", "venue_name")}},
    {"doctype": "WD Pickup", "sheet_name": "Pickups", "natural_key": ["guest", "eta"],
     "links": {"guest": ("WD Guest", "household_name"), "vehicle": ("WD Vehicle", "vehicle_number")}},
    {"doctype": "WD Crate", "sheet_name": "Crates", "natural_key": ["crate_no"],
     "links": {"destination_venue": ("WD Venue", "venue_name")}},
    {"doctype": "WD Shagun Entry", "sheet_name": "ShagunEntries", "natural_key": ["guest", "function", "received_by"],
     "links": {"guest": ("WD Guest", "household_name"), "function": ("WD Function", "function_name")}},
    {"doctype": "WD Approval Matrix Entry", "sheet_name": "ApprovalMatrix", "natural_key": ["situation"]},
    {"doctype": "WD Risk", "sheet_name": "Risks", "natural_key": ["title"]},
    {"doctype": "WD Gap Note", "sheet_name": "GapNotes", "natural_key": ["title"]},
]


def _sheet_fieldnames(doctype):
    # "wedding" is always injected server-side from the import call's target
    # wedding, never read from the sheet — a stray value in that column
    # would silently reassign a row to the wrong tenant.
    meta = frappe.get_meta(doctype)
    fields = [f for f in meta.fields if f.fieldname != "wedding"]
    return [f.fieldname for f in fields if f.fieldtype != "Table MultiSelect"] + \
        [f.fieldname for f in fields if f.fieldtype == "Table MultiSelect"]


def build_template_workbook() -> Workbook:
    wb = Workbook()
    wb.remove(wb.active)
    for sheet in SHEETS:
        ws = wb.create_sheet(sheet["sheet_name"])
        ws.append(_sheet_fieldnames(sheet["doctype"]))
    return wb


def _resolve_link(wedding, doctype, lookup_field, value, cache):
    if not value:
        return None, None
    key = (doctype, str(value).strip().lower())
    if key in cache:
        return cache[key], None
    name = frappe.db.get_value(doctype, {"wedding": wedding, lookup_field: value}, "name")
    if not name:
        return None, f"{doctype} '{value}' not found — import {doctype} sheet first"
    cache[key] = name
    return name, None


def run_import(wedding: str, file_path: str, import_job: str = None):
    wb = load_workbook(file_path, data_only=True)
    link_cache = {}
    totals = {"rows_total": 0, "rows_succeeded": 0, "rows_failed": 0}
    errors = []
    sheets_processed = []

    for sheet_cfg in SHEETS:
        sheet_name = sheet_cfg["sheet_name"]
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        headers = [str(h).strip() for h in rows[0] if h is not None]
        sheet_result = {"sheet": sheet_name, "doctype": sheet_cfg["doctype"], "succeeded": 0, "failed": 0}

        for row_idx, raw_row in enumerate(rows[1:], start=2):
            row = dict(zip(headers, raw_row))
            if not any(v not in (None, "") for v in row.values()):
                continue
            totals["rows_total"] += 1
            try:
                _import_row(wedding, sheet_cfg, row, link_cache)
                totals["rows_succeeded"] += 1
                sheet_result["succeeded"] += 1
            except Exception as e:  # noqa: BLE001 — one bad row must not abort the batch
                totals["rows_failed"] += 1
                sheet_result["failed"] += 1
                errors.append({"sheet": sheet_name, "row": row_idx, "error": str(e)})

        sheets_processed.append(sheet_result)

    if import_job:
        frappe.db.set_value("WD Import Job", import_job, {
            "status": "Done" if totals["rows_failed"] == 0 else "Done",
            "rows_total": totals["rows_total"],
            "rows_succeeded": totals["rows_succeeded"],
            "rows_failed": totals["rows_failed"],
            "error_log": json.dumps(errors),
        })
        frappe.db.commit()

    return {**totals, "sheets_processed": sheets_processed, "errors": errors}


def _import_row(wedding, sheet_cfg, row, link_cache):
    doctype = sheet_cfg["doctype"]
    links = sheet_cfg.get("links", {})
    multiselects = sheet_cfg.get("multiselects", {})

    data = {"wedding": wedding}
    for field, value in row.items():
        if field in ("wedding", None) or field in links or field in multiselects or value in (None, ""):
            continue
        data[field] = value

    for field, (link_doctype, lookup_field) in links.items():
        raw_value = row.get(field)
        resolved, err = _resolve_link(wedding, link_doctype, lookup_field, raw_value, link_cache)
        if err:
            raise ValueError(err)
        data[field] = resolved

    multiselect_rows = {}
    for field, (link_doctype, lookup_field) in multiselects.items():
        raw_value = row.get(field)
        if not raw_value:
            continue
        names = []
        for part in str(raw_value).split(","):
            part = part.strip()
            if not part:
                continue
            resolved, err = _resolve_link(wedding, link_doctype, lookup_field, part, link_cache)
            if err:
                raise ValueError(err)
            names.append(resolved)
        multiselect_rows[field] = names

    natural_key = sheet_cfg["natural_key"]
    filters = {"wedding": wedding}
    for key_field in natural_key:
        filters[key_field] = data.get(key_field)

    existing_name = frappe.db.get_value(doctype, filters, "name")
    if existing_name:
        doc = frappe.get_doc(doctype, existing_name)
        doc.update(data)
    else:
        doc = frappe.new_doc(doctype)
        doc.update(data)

    for field, names in multiselect_rows.items():
        link_fieldname_in_child = _multiselect_child_link_field(doctype, field)
        doc.set(field, [])
        for name in names:
            doc.append(field, {link_fieldname_in_child: name})

    doc.save(ignore_permissions=True)


def _multiselect_child_link_field(doctype, fieldname):
    meta = frappe.get_meta(doctype)
    df = meta.get_field(fieldname)
    child_meta = frappe.get_meta(df.options)
    link_fields = [f.fieldname for f in child_meta.fields if f.fieldtype == "Link"]
    return link_fields[0]
