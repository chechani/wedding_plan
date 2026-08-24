# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import today

from wedding_plan.task_logic import resolve_contact_point

_ASSIGNMENT_FIELD = {
	"Team": "assigned_team",
	"Vendor": "assigned_vendor",
	"Person": "assigned_person",
}


class WDTask(Document):
	def validate(self):
		self._resolve_assignment()
		self._resolve_contact()
		self._apply_status_change()

	def _resolve_assignment(self):
		required_field = _ASSIGNMENT_FIELD.get(self.assigned_to_type)
		if self.assigned_to_type and not self.get(required_field):
			frappe.throw(_("Select {0} for this task's assignment.").format(required_field))

		for other_type, field in _ASSIGNMENT_FIELD.items():
			if other_type != self.assigned_to_type:
				self.set(field, None)

	def _resolve_contact(self):
		contact = resolve_contact_point(
			self.assigned_to_type,
			assigned_team=self.assigned_team,
			assigned_vendor=self.assigned_vendor,
			assigned_person=self.assigned_person,
		)
		self.contact_name = contact["contact_name"]
		self.contact_phone = contact["contact_phone"]
		self.contact_secondary_name = contact["contact_secondary_name"]
		self.contact_secondary_phone = contact["contact_secondary_phone"]

	def _apply_status_change(self):
		if self.status == "Blocked" and not self.blocked_reason:
			frappe.throw(_("Blocked tasks need a reason."))

		if self.status == "Done":
			if not self.completed_date:
				self.completed_date = today()
		else:
			self.completed_date = None

		if self.status != "Blocked":
			self.blocked_reason = None
