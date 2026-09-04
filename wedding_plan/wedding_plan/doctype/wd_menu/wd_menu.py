# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class WDMenu(Document):
	def validate(self):
		self._require_an_anchor()
		self._default_expected_count()

	def _require_an_anchor(self):
		"""A menu attached to nothing is not orderable in any view — needs a
		function, a formal meal session, or at minimum a standalone label."""
		if not (self.function or self.meal_session or self.service_label):
			frappe.throw(_("Set a Function, a Meal Session, or a Service Label for this menu."))

	def _default_expected_count(self):
		if self.meal_session and not self.expected_count:
			self.expected_count = frappe.db.get_value("WD Meal Session", self.meal_session, "guaranteed_plates")
