# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from wedding_plan.task_logic import enforce_polymorphic_assignment, resolve_contact_point

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
		enforce_polymorphic_assignment(self, self.responsible_type, _RESPONSIBLE_FIELD, "this item's responsibility")

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
