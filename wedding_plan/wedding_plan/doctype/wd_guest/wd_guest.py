# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class WDGuest(Document):
	def on_update(self):
		self._sync_member_attendance()

	def _sync_member_attendance(self):
		"""When a household is marked invited to a function, every current
		member of that household should have an Invited-status attendance
		row — so per-function headcounts are accurate as soon as a household
		is marked invited, without a planner having to create rows by hand.
		Never removes rows if a function is later dropped from the list, to
		preserve history."""
		invited_functions = [row.wd_function for row in (self.functions_invited or [])]
		if not invited_functions:
			return

		members = frappe.get_all("WD Guest Member", filters={"guest": self.name}, pluck="name")
		if not members:
			return

		existing = {
			(row.guest_member, row.function)
			for row in frappe.get_all(
				"WD Guest Member Function",
				filters={"household": self.name, "function": ["in", invited_functions]},
				fields=["guest_member", "function"],
			)
		}

		for member in members:
			for function in invited_functions:
				if (member, function) in existing:
					continue
				frappe.get_doc(
					{
						"doctype": "WD Guest Member Function",
						"wedding": self.wedding,
						"guest_member": member,
						"household": self.name,
						"function": function,
						"status": "Invited",
					}
				).insert(ignore_permissions=True)
