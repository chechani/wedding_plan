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
