"""
Shared, centralized rules for the Tasks & Coordination module — contact-point
resolution for a task's polymorphic assignee. Kept out of the DocType
controller and out of api/tasks.py so both can share the same rule instead of
re-implementing it (mirrors wedding_plan/invitation_logic.py's precedent).

WD Team carries two named contacts (member_a_*/member_b_*) with no field
designating either as "the" primary — member_a is treated as primary purely
by field position. If WD Team ever gains a real primary-contact field, this
is the one place that needs updating.
"""
import frappe
from frappe import _


def enforce_polymorphic_assignment(doc, type_value, field_by_type, label):
	"""Shared validate()-time rule for a doc with a polymorphic
	type/assignee pair (WD Task's assigned_to_type/assigned_*, WD Function
	Checklist Item's responsible_type/responsible_*): the field naming the
	selected type is required, and every other type's field is cleared so a
	stale value from a previous type selection can't linger.
	`label` names the assignment for the error message, e.g. "this task's
	assignment"."""
	required_field = field_by_type.get(type_value)
	if type_value and not doc.get(required_field):
		frappe.throw(_("Select {0} for {1}.").format(required_field, label))

	for other_type, field in field_by_type.items():
		if other_type != type_value:
			doc.set(field, None)


def batch_lookup_titles(doctype, ids, title_field):
	"""{name: title_field value} for the given ids in one query — the
	"batch-resolve a link column's display name" step every board/enrich
	view (api/tasks.py, api/checklist.py) needs for each Link field it joins
	against, so it isn't hand-rolled per call site."""
	ids = [i for i in set(ids) if i]
	if not ids:
		return {}
	rows = frappe.get_all(doctype, filters={"name": ["in", ids]}, fields=["name", title_field])
	return {row.name: row.get(title_field) for row in rows}


def resolve_polymorphic_name(type_value, field_by_type, row, name_maps_by_type):
	"""Given a row with a polymorphic `type_value` (e.g. "Team"/"Vendor") and,
	per type, which field on `row` holds the reference and which
	{ref: display name} map to look it up in, returns the resolved display
	name (or None if unresolvable)."""
	if not type_value or type_value not in field_by_type:
		return None
	ref = row.get(field_by_type[type_value])
	return name_maps_by_type.get(type_value, {}).get(ref)


def resolve_contact_point(assigned_to_type, assigned_team=None, assigned_vendor=None, assigned_person=None):
	"""Returns {"contact_name","contact_phone","contact_secondary_name","contact_secondary_phone"},
	all None if nothing resolvable for the given assignment."""
	empty = {
		"contact_name": None,
		"contact_phone": None,
		"contact_secondary_name": None,
		"contact_secondary_phone": None,
	}

	if assigned_to_type == "Vendor" and assigned_vendor:
		vendor = frappe.db.get_value("WD Vendor", assigned_vendor, ["contact_name", "contact_phone"], as_dict=True)
		if not vendor:
			return empty
		return {
			"contact_name": vendor.contact_name,
			"contact_phone": vendor.contact_phone,
			"contact_secondary_name": None,
			"contact_secondary_phone": None,
		}

	if assigned_to_type == "Person" and assigned_person:
		user = frappe.db.get_value("User", assigned_person, ["full_name", "mobile_no", "phone"], as_dict=True)
		if not user:
			return empty
		return {
			"contact_name": user.full_name,
			"contact_phone": user.mobile_no or user.phone,
			"contact_secondary_name": None,
			"contact_secondary_phone": None,
		}

	if assigned_to_type == "Team" and assigned_team:
		team = frappe.db.get_value(
			"WD Team",
			assigned_team,
			["member_a_name", "member_a_contact", "member_b_name", "member_b_contact"],
			as_dict=True,
		)
		if not team:
			return empty
		return {
			"contact_name": team.member_a_name,
			"contact_phone": team.member_a_contact,
			"contact_secondary_name": team.member_b_name,
			"contact_secondary_phone": team.member_b_contact,
		}

	return empty
