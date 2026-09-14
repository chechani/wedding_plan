"""
Guest Family importer — one flat sheet, upserted on Mobile.

Deliberately separate from `import_excel.py`'s multi-sheet workbook importer,
because the two solve different problems:

  - **One sheet, human labels.** Column headers here are the labels a planner
    already reads on the Guest Family page ("Household", "Mobile", "Sub
    Group", "VIP Protocol") — not fieldnames. The guest lists that actually
    arrive are made in Excel by the families themselves; re-typing them into
    a fieldname-headed template is precisely the work this removes. Headers
    are matched against *both* label and fieldname, so a sheet exported from
    the multi-sheet template still imports here unchanged.

  - **Mobile is the identity.** `import_excel.py` keys `WD Guest` on
    `(household_name, primary_phone)`, so correcting a household's spelling
    on the second import creates a second row. Here the phone number alone
    decides: same number -> update that family, new number -> create one.
    Matching is on *normalised digits*, so "+91 93021 05067", "093021 05067"
    and "9302105067" are one household, not three.

  - **A blank cell never writes.** Empty cells are dropped from the payload
    entirely rather than written as "". A sheet carrying only Mobile + Rooms
    Needed tops up 400 existing families without blanking the 20 columns it
    doesn't mention. The corollary — you cannot *clear* a field by blanking
    its cell — is the deliberate trade: an accidental half-filled sheet is
    far commoner than a deliberate mass-blanking.

A row is all-or-nothing: if any cell in it fails to coerce, nothing from that
row is written, so a half-applied household can never exist. One bad row
never aborts the batch.

`dry_run=True` runs every validation and lookup and writes nothing — that is
what backs the preview the UI shows before anyone commits an 800-row sheet.
"""

import re
from datetime import date, datetime, time

import frappe
from frappe.utils import get_datetime, getdate
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from wedding_plan.setup.doctype_specs import WEDDING_SCOPED_DOCTYPES

GUEST_DOCTYPE = "WD Guest"

#: The column the upsert keys on. Everything else about a row can change.
MATCH_FIELD = "primary_phone"

#: Never read from the sheet, whatever the header says.
#: `wedding` is injected server-side from the import's target wedding — a
#: stray value in that column would silently reassign a household to another
#: tenant. `attachments` is a child table with no sensible flat-cell form.
IGNORED_FIELDS = {"wedding", "attachments", "naming_series"}

#: Fieldtypes that carry no data and so never become columns.
LAYOUT_FIELDTYPES = {
	"Section Break",
	"Column Break",
	"Tab Break",
	"HTML",
	"Heading",
	"Fold",
	"Button",
	"Image",
	"Table",
}

#: The order the template ships in and the order the PDF spec listed —
#: everything else `WD Guest` accepts is appended after these by
#: `build_guest_template_workbook()`, so the sheet stays open-ended without
#: burying the columns anyone actually fills.
TEMPLATE_LEAD_FIELDS = [
	"household_name",
	"side",
	"invitation_prefix",
	"invitation_name",
	"invitation_suffix",
	"primary_phone",
	"alternate_phone",
	"address",
	"city",
	"pincode",
	"category",
	"sub_group",
	"pax",
	"kids",
	"rooms_needed",
	"special_needs",
	"vip_protocol",
]

#: Headers seen in real sheets that match neither a fieldname nor a label.
#: Keys are compared after `_norm()`, so punctuation and case don't matter.
#: A bare "Name" is deliberately absent — it is as likely to mean the
#: invitation name as the household, and guessing wrong mislabels every row.
HEADER_ALIASES = {
	"household name": "household_name",
	"guest family": "household_name",
	"family": "household_name",
	"family name": "household_name",
	"mobile no": "primary_phone",
	"mobile number": "primary_phone",
	"phone": "primary_phone",
	"phone no": "primary_phone",
	"contact": "primary_phone",
	"contact no": "primary_phone",
	"whatsapp": "primary_phone",
	"alt phone": "alternate_phone",
	"alternate no": "alternate_phone",
	"secondary phone": "alternate_phone",
	"pin code": "pincode",
	"pin": "pincode",
	"sub group name": "sub_group",
	"subgroup": "sub_group",
	"group": "sub_group",
	"vip": "vip_protocol",
	"no of pax": "pax",
	"members": "pax",
	"rooms": "rooms_needed",
	"room needed": "rooms_needed",
	"stay": "stay_required",
	"rsvp": "rsvp_status",
	"patrika": "patrika_status",
	"invited to": "functions_invited",
	"functions": "functions_invited",
}

#: How to find an existing link target from the human-readable text in a cell.
#: Anything not listed falls back to the target doctype's title field.
LINK_LOOKUP_FIELDS = {
	"WD City": "city",
	"WD Sub Group": "sub_group_name",
	"WD Venue": "venue_name",
	"WD Patrika Delivery Mode": "delivery_mode",
	"WD Function": "function_type",
}

#: Link targets this importer may create on the fly when
#: `create_missing_links` is on. Restricted to pure label masters — a doctype
#: whose every mandatory field is the label itself, so an auto-created row
#: can't be a half-built record. `WD Venue` is excluded on purpose: it needs
#: a city and a location nobody puts in a guest sheet.
AUTO_CREATABLE_LINKS = {"WD City", "WD Sub Group"}

#: Compared after `_squash()`, so "Yes." / "YES" / " yes " all land.
_TRUE_WORDS = {"yes", "y", "true", "t", "1", "haan", "ha", "x", "on"}
_FALSE_WORDS = {"no", "n", "false", "f", "0", "nahi", "off", "none", "na"}

#: Guard against a sheet whose formatting extends far past its data —
#: openpyxl will happily iterate a million empty rows otherwise.
_BLANK_RUN_LIMIT = 200

#: How many per-row entries a result may carry back to the browser. Rows with
#: a problem are never dropped; clean rows fill whatever budget is left. An
#: 800-household sheet otherwise returns a payload nobody on 4G wants.
_MAX_DETAIL_ROWS = 300

_SHEET_NAME_HINTS = {"guest family", "guest families", "guests", "guest", "guest list"}


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def _norm(text) -> str:
	"""Lowercase, punctuation-insensitive form used to compare headers.

	"Sub-Group", "sub group" and "SUB_GROUP" all collapse to "sub group".
	"""
	return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _squash(text) -> str:
	"""Like `_norm()` but drops separators entirely — "Dr." == "Dr", "Smt." ==
	"Smt". Used as the loose fallback when matching Select options."""
	return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


_TRUE_SQUASHED = {_squash(w) for w in _TRUE_WORDS}
_FALSE_SQUASHED = {_squash(w) for w in _FALSE_WORDS}


def normalise_phone(value) -> str:
	"""Digits only, reduced to the national number, for matching *and* storage.

	Excel hands back a phone column typed as a number as an `int` (or a
	`float`, hence the `is_integer()` step — `str(9302105067.0)` would
	otherwise be stored with a trailing ".0" and match nothing).

	Country/trunk prefixes are stripped so the same person entered four
	different ways is one household. Anything that isn't a recognisable
	Indian 10-digit number is left as its full digit string rather than
	truncated — an international number stays intact, it just won't collapse
	onto its own variants.
	"""
	if value is None:
		return ""
	if isinstance(value, float) and value.is_integer():
		value = int(value)
	digits = re.sub(r"\D", "", str(value))
	if len(digits) == 11 and digits.startswith("0"):
		return digits[1:]
	if len(digits) == 12 and digits.startswith("91"):
		return digits[2:]
	if len(digits) == 13 and digits.startswith("091"):
		return digits[3:]
	return digits


def _is_blank(value) -> bool:
	return value is None or (isinstance(value, str) and not value.strip())


# ---------------------------------------------------------------------------
# Header -> fieldname mapping
# ---------------------------------------------------------------------------


def _importable_fields():
	"""Every `WD Guest` field a sheet may set, in DocType field order."""
	meta = frappe.get_meta(GUEST_DOCTYPE)
	return [
		df
		for df in meta.fields
		if df.fieldname not in IGNORED_FIELDS
		and df.fieldtype not in LAYOUT_FIELDTYPES
		and not df.read_only
	]


def _header_map():
	"""Normalised header text -> fieldname.

	Fieldnames and labels both register, fieldnames first so a label that
	happens to collide with another field's fieldname can never hijack it.
	`HEADER_ALIASES` fills in last and never overrides a real one.
	"""
	fields = _importable_fields()
	mapping = {}
	for df in fields:
		mapping.setdefault(_norm(df.fieldname), df.fieldname)
	for df in fields:
		if df.label:
			mapping.setdefault(_norm(df.label), df.fieldname)
	for alias, fieldname in HEADER_ALIASES.items():
		mapping.setdefault(_norm(alias), fieldname)
	return mapping


def build_guest_template_workbook() -> Workbook:
	"""A blank one-sheet template headed with the *labels* of every importable
	`WD Guest` field, lead columns first.

	Generated from the live meta rather than a hard-coded list, so the
	template can never drift from what the importer accepts."""
	fields = {df.fieldname: df for df in _importable_fields()}
	ordered = [fields[f] for f in TEMPLATE_LEAD_FIELDS if f in fields]
	ordered += [df for name, df in fields.items() if name not in TEMPLATE_LEAD_FIELDS]

	wb = Workbook()
	ws = wb.active
	ws.title = "Guest Family"
	ws.append([df.label or df.fieldname for df in ordered])
	for cell in ws[1]:
		cell.font = Font(bold=True)
	for idx, df in enumerate(ordered, start=1):
		ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = max(
			12, min(28, len(df.label or df.fieldname) + 4)
		)
	ws.freeze_panes = "A2"
	return wb


# ---------------------------------------------------------------------------
# Sheet reading
# ---------------------------------------------------------------------------


def _pick_sheet(wb):
	"""The sheet named like a guest list, else the first one in the book."""
	for name in wb.sheetnames:
		if _norm(name) in _SHEET_NAME_HINTS:
			return wb[name]
	return wb[wb.sheetnames[0]]


def _read_sheet(ws, header_map):
	"""Find the header row and return (header_row_no, columns, data_rows).

	The header is *not* assumed to be row 1: real sheets carry a title, a
	blank line, sometimes a merged banner. The row in the first ten that maps
	the most known columns wins, earliest on a tie.

	`columns` is [(column_index, header_text, fieldname_or_None)] in sheet
	order — unmapped columns are kept so the caller can report them rather
	than silently swallowing a misspelt header.
	"""
	rows = []
	blank_run = 0
	for raw in ws.iter_rows(values_only=True):
		if raw is None or all(_is_blank(v) for v in raw):
			blank_run += 1
			if blank_run >= _BLANK_RUN_LIMIT:
				break
			rows.append(raw)
			continue
		blank_run = 0
		rows.append(raw)

	best_idx, best_hits = None, 0
	for idx, raw in enumerate(rows[:10]):
		hits = sum(1 for cell in (raw or []) if not _is_blank(cell) and _norm(cell) in header_map)
		if hits > best_hits:
			best_idx, best_hits = idx, hits
	if best_idx is None or best_hits < 2:
		return None, [], []

	header_row = rows[best_idx]
	columns = []
	seen_fields = set()
	for col_idx, cell in enumerate(header_row):
		if _is_blank(cell):
			continue
		fieldname = header_map.get(_norm(cell))
		# A sheet with "Mobile" and "Phone" both present would otherwise have
		# the second column silently overwrite the first.
		if fieldname and fieldname in seen_fields:
			fieldname = None
		if fieldname:
			seen_fields.add(fieldname)
		columns.append((col_idx, str(cell).strip(), fieldname))

	data = []
	for offset, raw in enumerate(rows[best_idx + 1 :], start=best_idx + 2):
		if raw is None or all(_is_blank(v) for v in raw):
			continue  # a wholly empty row is skipped, never reported as an error
		data.append((offset, raw))
	return best_idx + 1, columns, data


# ---------------------------------------------------------------------------
# Per-run context
# ---------------------------------------------------------------------------


class _Context:
	def __init__(self, wedding, create_missing_links, dry_run):
		self.wedding = wedding
		self.create_missing_links = create_missing_links
		self.dry_run = dry_run
		self.meta = frappe.get_meta(GUEST_DOCTYPE)
		self.link_cache = {}
		#: Link rows this run created (or, in a dry run, would create).
		self.created_links = []
		#: Dry-run only: (doctype, value) already counted as "would create".
		self.pending_links = set()
		#: normalised phone -> {"name", "household_name"} for this wedding.
		self.phone_index = {}
		#: normalised phone -> sheet row that first claimed it, so a sheet
		#: listing the same number twice reports the collision instead of
		#: quietly letting the later row win in silence.
		self.rows_by_phone = {}
		self._load_phone_index()

	def _load_phone_index(self):
		existing = frappe.get_all(
			GUEST_DOCTYPE,
			filters={"wedding": self.wedding},
			fields=["name", "household_name", "primary_phone"],
			limit_page_length=0,
		)
		for row in existing:
			key = normalise_phone(row.primary_phone)
			if not key:
				continue
			# First one wins. Duplicates already in the database are a
			# pre-existing data problem; picking the oldest keeps repeat
			# imports landing on the same record instead of alternating.
			self.phone_index.setdefault(key, {"name": row.name, "household_name": row.household_name})


def _wedding_scoped(doctype) -> bool:
	return doctype in WEDDING_SCOPED_DOCTYPES


def _link_lookup_field(doctype) -> str:
	if doctype in LINK_LOOKUP_FIELDS:
		return LINK_LOOKUP_FIELDS[doctype]
	return frappe.get_meta(doctype).get_title_field() or "name"


def _resolve_link(ctx, doctype, value):
	"""Human-readable cell text -> the linked doc's `name`.

	Returns `(name, error)`. In a dry run a link that *would* be created comes
	back as `(None, None)` with the intent recorded on `ctx.created_links` —
	nothing is written, and the caller doesn't treat it as a row failure.
	"""
	raw = str(value).strip()
	if not raw:
		return None, None
	cache_key = (doctype, raw.lower())
	if cache_key in ctx.link_cache:
		return ctx.link_cache[cache_key], None

	lookup_field = _link_lookup_field(doctype)
	filters = {lookup_field: raw}
	if _wedding_scoped(doctype):
		filters["wedding"] = ctx.wedding
	name = frappe.db.get_value(doctype, filters, "name")

	if not name:
		# The sheet may carry the doc id itself (a re-import of an export).
		by_name = frappe.db.get_value(
			doctype,
			{"name": raw, **({"wedding": ctx.wedding} if _wedding_scoped(doctype) else {})},
			"name",
		)
		name = by_name or None

	if not name:
		if doctype not in AUTO_CREATABLE_LINKS or not ctx.create_missing_links:
			hint = (
				"tick “create missing cities and sub-groups”, or add it first"
				if doctype in AUTO_CREATABLE_LINKS
				else f"create the {doctype} record first"
			)
			return None, f"{doctype} “{raw}” doesn't exist — {hint}"
		if ctx.dry_run:
			# `link_cache` can't absorb this — there is no name to cache — so
			# a second row naming the same missing sub-group would otherwise
			# be counted again, and the preview would promise to create four
			# sub-groups where the real run creates one.
			if cache_key not in ctx.pending_links:
				ctx.pending_links.add(cache_key)
				ctx.created_links.append({"doctype": doctype, "value": raw})
			return None, None
		ctx.created_links.append({"doctype": doctype, "value": raw})
		doc = frappe.new_doc(doctype)
		doc.set(lookup_field, raw)
		if _wedding_scoped(doctype):
			doc.wedding = ctx.wedding
		doc.insert(ignore_permissions=True)
		name = doc.name

	ctx.link_cache[cache_key] = name
	return name, None


def _multiselect_child_link(fieldname):
	"""(child fieldname, target doctype) for a Table MultiSelect column —
	e.g. "Invited To" -> ("wd_function", "WD Function")."""
	df = frappe.get_meta(GUEST_DOCTYPE).get_field(fieldname)
	child_meta = frappe.get_meta(df.options)
	link_df = next(f for f in child_meta.fields if f.fieldtype == "Link")
	return link_df.fieldname, link_df.options


def _coerce(ctx, df, value):
	"""One cell -> the value Frappe wants, or `(None, message)`.

	The message is written for the person holding the spreadsheet, naming the
	column by its label and quoting what they actually typed.
	"""
	label = df.label or df.fieldname
	fieldtype = df.fieldtype

	if fieldtype == "Check":
		if isinstance(value, (bool, int, float)):
			return (1 if value else 0), None
		word = _squash(value)
		if word in _TRUE_SQUASHED:
			return 1, None
		if word in _FALSE_SQUASHED:
			return 0, None
		return None, f"{label}: “{value}” isn't a yes/no"

	# `cint`/`flt` are deliberately *not* used here: both swallow garbage and
	# return 0, so a Pax column reading "four" would import as zero people.
	if fieldtype in ("Int", "Long Int"):
		try:
			return int(float(str(value).strip().replace(",", ""))), None
		except (ValueError, TypeError):
			return None, f"{label}: “{value}” isn't a whole number"

	if fieldtype in ("Float", "Currency", "Percent"):
		try:
			return float(str(value).strip().replace(",", "")), None
		except (ValueError, TypeError):
			return None, f"{label}: “{value}” isn't a number"

	if fieldtype == "Date":
		try:
			return getdate(value).strftime("%Y-%m-%d"), None
		except Exception:
			return None, f"{label}: “{value}” isn't a date (use a real Excel date cell, or DD-MM-YYYY)"

	if fieldtype == "Datetime":
		if isinstance(value, datetime):
			return value.strftime("%Y-%m-%d %H:%M:%S"), None
		if isinstance(value, date):
			return f"{value.strftime('%Y-%m-%d')} 00:00:00", None
		try:
			return get_datetime(str(value).strip()).strftime("%Y-%m-%d %H:%M:%S"), None
		except Exception:
			return None, f"{label}: “{value}” isn't a date and time"

	if fieldtype == "Time":
		if isinstance(value, (time, datetime)):
			return value.strftime("%H:%M:%S"), None
		return str(value).strip(), None

	if fieldtype == "Select":
		options = [o.strip() for o in (df.options or "").split("\n") if o.strip()]
		raw = str(value).strip()
		if not options:
			return raw, None
		for option in options:
			if option.lower() == raw.lower():
				return option, None
		for option in options:  # loose: "Dr" matches "Dr.", "Smt" matches "Smt."
			if _squash(option) == _squash(raw):
				return option, None
		return None, f"{label}: “{raw}” isn't one of {', '.join(options)}"

	if fieldtype == "Link":
		return _resolve_link(ctx, df.options, value)

	if fieldtype == "Table MultiSelect":
		_, target_doctype = _multiselect_child_link(df.fieldname)
		names = []
		for part in str(value).split(","):
			part = part.strip()
			if not part:
				continue
			resolved, err = _resolve_link(ctx, target_doctype, part)
			if err:
				return None, f"{label}: {err}"
			if resolved:
				names.append(resolved)
		# An empty list would *clear* the existing invites; a cell we couldn't
		# resolve a single entry from must leave them alone instead.
		return (names or None), None

	# Data / Small Text / Text / Long Text / Text Editor / Phone / ...
	if isinstance(value, float) and value.is_integer():
		value = int(value)  # a Pincode column typed as a number
	text = str(value).strip()
	if df.fieldname in (MATCH_FIELD, "alternate_phone"):
		# Stored in the same normalised form the match key uses, so search,
		# the card's tel: link and the next import all see one format.
		return normalise_phone(text) or text, None
	return text, None


# ---------------------------------------------------------------------------
# The import itself
# ---------------------------------------------------------------------------


def import_guest_families(
	wedding: str,
	file_path: str,
	dry_run: bool = False,
	create_missing_links: bool = True,
	import_job: str | None = None,
):
	"""Upsert `WD Guest` rows from one flat sheet, keyed on Mobile.

	`dry_run=True` validates and resolves everything, writes nothing, and
	returns the identical result shape — that is what the preview renders.
	"""
	wb = load_workbook(file_path, data_only=True, read_only=True)
	try:
		ws = _pick_sheet(wb)
		# Read the title *before* close(): a read-only worksheet is backed by
		# the still-open zip and is not safely usable afterwards.
		sheet_title = ws.title
		header_row_no, columns, data_rows = _read_sheet(ws, _header_map())
	finally:
		wb.close()

	mapped = {header: fieldname for _, header, fieldname in columns if fieldname}
	ignored_columns = [header for _, header, fieldname in columns if not fieldname]

	summary = {
		"sheet": sheet_title,
		"header_row": header_row_no,
		"columns_mapped": mapped,
		"columns_ignored": ignored_columns,
		"rows_total": 0,
		"rows_created": 0,
		"rows_updated": 0,
		"rows_skipped": 0,
		"rows_failed": 0,
		"dry_run": bool(dry_run),
	}

	if header_row_no is None:
		summary["error"] = (
			"No header row found. The first ten rows of the sheet carry no recognisable "
			"column names — download the template and use its headers."
		)
		return {**summary, "rows": [], "rows_truncated": 0, "links_created": []}
	if MATCH_FIELD not in mapped.values():
		summary["error"] = (
			"No “Mobile” column found. That column is what decides whether a row updates "
			"an existing guest family or creates a new one, so the import can't run without it."
		)
		return {**summary, "rows": [], "rows_truncated": 0, "links_created": []}

	ctx = _Context(wedding, create_missing_links, dry_run)
	results = []

	for row_no, raw_row in data_rows:
		summary["rows_total"] += 1
		results.append(_process_row(ctx, columns, row_no, raw_row))

	for entry in results:
		summary[
			{
				"create": "rows_created",
				"update": "rows_updated",
				"skip": "rows_skipped",
				"error": "rows_failed",
			}[entry["action"]]
		] += 1

	detail, truncated = _trim_detail(results)
	result = {
		**summary,
		"rows": detail,
		"rows_truncated": truncated,
		"links_created": ctx.created_links,
	}

	if import_job and not dry_run:
		frappe.db.set_value(
			"WD Import Job",
			import_job,
			{
				"status": "Done" if summary["rows_failed"] == 0 else "Failed",
				"rows_total": summary["rows_total"],
				"rows_succeeded": summary["rows_created"] + summary["rows_updated"],
				"rows_failed": summary["rows_failed"] + summary["rows_skipped"],
				"error_log": frappe.as_json(
					[r for r in results if r["action"] in ("error", "skip")]
				),
			},
		)
		frappe.db.commit()

	return result


def _process_row(ctx, columns, row_no, raw_row):
	"""One sheet row -> one result entry. Never raises: a row that blows up is
	a reported failure, not an aborted batch."""
	values = {}
	errors = []

	for col_idx, _header, fieldname in columns:
		if not fieldname:
			continue
		cell = raw_row[col_idx] if col_idx < len(raw_row) else None
		if _is_blank(cell):
			continue  # a blank cell is never written — see the module docstring
		df = ctx.meta.get_field(fieldname)
		coerced, err = _coerce(ctx, df, cell)
		if err:
			errors.append(err)
		elif coerced is not None:
			values[fieldname] = coerced

	if not values:
		return _entry(row_no, "skip", message="Every mapped cell in this row is empty.")

	household = values.get("household_name") or ""
	phone_key = normalise_phone(values.get(MATCH_FIELD))

	if not phone_key:
		return _entry(
			row_no,
			"skip",
			household=household,
			message=(
				"Mobile is blank. Every row is matched on its mobile number, so a row "
				"without one would create a fresh duplicate on every import."
			),
		)
	if len(phone_key) < 10:
		return _entry(
			row_no,
			"skip",
			household=household,
			mobile=phone_key,
			message=f"Mobile “{phone_key}” is only {len(phone_key)} digits — needs at least 10.",
		)

	if errors:
		return _entry(row_no, "error", household=household, mobile=phone_key, message="; ".join(errors))

	existing = ctx.phone_index.get(phone_key)
	first_claim = ctx.rows_by_phone.get(phone_key)
	if existing is None and not household:
		return _entry(
			row_no,
			"error",
			mobile=phone_key,
			message="Household is blank, and this mobile isn't on the list yet — a new guest family needs a name.",
		)

	action = "update" if existing else "create"
	note = None
	if first_claim:
		note = f"Row {first_claim} in this sheet has the same mobile — this row edits the same guest family."
	ctx.rows_by_phone[phone_key] = row_no

	if ctx.dry_run:
		# Register the number even though nothing is written, so a sheet that
		# lists the same new mobile twice previews as create-then-update —
		# which is what the real run will do.
		ctx.phone_index.setdefault(phone_key, {"name": None, "household_name": household})
		return _entry(
			row_no,
			action,
			household=household or (existing or {}).get("household_name", ""),
			mobile=phone_key,
			guest=(existing or {}).get("name"),
			fields=sorted(values.keys()),
			message=note,
		)

	# A row-level SAVEPOINT, not a bare rollback: `doc.save()` can fail
	# half-written (parent inserted, child table not), and rolling the whole
	# transaction back would throw away every household imported before this
	# one. The savepoint undoes exactly this row.
	savepoint = f"guest_import_row_{row_no}"
	frappe.db.savepoint(savepoint)
	try:
		if existing:
			doc = frappe.get_doc(GUEST_DOCTYPE, existing["name"])
		else:
			doc = frappe.new_doc(GUEST_DOCTYPE)
			doc.wedding = ctx.wedding

		multiselects = {k: v for k, v in values.items() if isinstance(v, list)}
		doc.update({k: v for k, v in values.items() if k not in multiselects})
		for fieldname, names in multiselects.items():
			child_link, _ = _multiselect_child_link(fieldname)
			doc.set(fieldname, [])
			for name in names:
				doc.append(fieldname, {child_link: name})
		doc.save(ignore_permissions=True)
	except Exception as e:  # one bad row must not abort the batch
		frappe.db.rollback(save_point=savepoint)
		return _entry(
			row_no, "error", household=household, mobile=phone_key, message=str(e).strip() or repr(e)
		)

	# Only index it once it is actually saved, so a later row carrying the
	# same number updates this record rather than trying to create a second.
	ctx.phone_index[phone_key] = {"name": doc.name, "household_name": doc.household_name}
	return _entry(
		row_no,
		action,
		household=doc.household_name or "",
		mobile=phone_key,
		guest=doc.name,
		fields=sorted(values.keys()),
		message=note,
	)


def _entry(row, action, household="", mobile="", guest=None, fields=None, message=None):
	return {
		"row": row,
		"action": action,
		"household": household,
		"mobile": mobile,
		"guest": guest,
		"fields": fields or [],
		"message": message,
	}


def _trim_detail(results):
	"""Cap the per-row detail sent to the browser without ever dropping a row
	that needs a human — problems are kept in full, clean rows fill the rest
	of the budget, and the whole thing goes back in sheet order."""
	if len(results) <= _MAX_DETAIL_ROWS:
		return results, 0
	problems = [r for r in results if r["action"] in ("error", "skip")][:_MAX_DETAIL_ROWS]
	budget = _MAX_DETAIL_ROWS - len(problems)
	clean = [r for r in results if r["action"] in ("create", "update")][:budget]
	kept = sorted(problems + clean, key=lambda r: r["row"])
	return kept, len(results) - len(kept)
