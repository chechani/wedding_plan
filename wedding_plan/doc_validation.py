# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

"""Small, generic validate()-time helpers shared across doctype controllers
that would otherwise each hand-roll the same "does this link field's own
parent link actually match?" check (WD Function's sub_venue vs venue,
WD Gifting's guest_member vs guest, WD Guest Member's guest vs wedding)."""

import frappe


def assert_child_belongs_to_parent(doctype, name, parent_field, expected_parent, message):
	"""Raises `message` if `name` (a doc of `doctype`) doesn't actually
	belong to `expected_parent` via its own `parent_field` link. Skips
	silently if either side is empty — nothing to check yet."""
	if not name or not expected_parent:
		return
	actual_parent = frappe.db.get_value(doctype, name, parent_field)
	if actual_parent != expected_parent:
		frappe.throw(message)
