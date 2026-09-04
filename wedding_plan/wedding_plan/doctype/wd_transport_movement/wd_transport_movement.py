# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class WDTransportMovement(Document):
	def validate(self):
		self._default_eta_current()

	def _default_eta_current(self):
		"""eta_current tracks the live expectation; eta_planned is the plan and
		is never touched here. The first time eta_planned is set, eta_current
		starts out equal to it — a delay update then only ever changes
		eta_current, never eta_planned."""
		if self.eta_planned and not self.eta_current:
			self.eta_current = self.eta_planned
