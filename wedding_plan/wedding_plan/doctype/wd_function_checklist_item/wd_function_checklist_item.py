# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from wedding_plan.task_logic import resolve_contact_point

_RESPONSIBLE_FIELD = {
	"Vendor": "responsible_vendor",
	"Team": "responsible_team",
}


class WDFunctionChecklistItem(Document):
	def validate(self):
		self._resolve_responsibility()
		self._resolve_contact()
		self._apply_status_change()

	def _resolve_responsibility(self):
		required_field = _RESPONSIBLE_FIELD.get(self.responsible_type)
		if self.responsible_type and not self.get(required_field):
			frappe.throw(_("Select {0} for this item's responsibility.").format(required_field))

		for other_type, field in _RESPONSIBLE_FIELD.items():
			if other_type != self.responsible_type:
				self.set(field, None)

	def _resolve_contact(self):
		contact = resolve_contact_point(
			self.responsible_type,
			assigned_team=self.responsible_team,
			assigned_vendor=self.responsible_vendor,
		)
		self.contact_name = contact["contact_name"]
		self.contact_phone = contact["contact_phone"]

	def _apply_status_change(self):
		if self.status == "Blocked" and not self.blocked_reason:
			frappe.throw(_("Blocked checklist items need a reason."))

		if self.status != "Blocked":
			self.blocked_reason = None
