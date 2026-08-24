# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class WDGuestMember(Document):
	def validate(self):
		self._check_household_wedding()
		self._reset_stale_access_level()

	def _check_household_wedding(self):
		household_wedding = frappe.db.get_value("WD Guest", self.guest, "wedding")
		if household_wedding != self.wedding:
			frappe.throw(_("This household belongs to a different wedding."))

	def _reset_stale_access_level(self):
		if not self.portal_enabled:
			self.portal_access_level = "None"
