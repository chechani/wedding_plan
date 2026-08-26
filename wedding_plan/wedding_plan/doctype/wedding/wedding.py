# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class Wedding(Document):
	def validate(self):
		names = (self.bride_name, self.groom_name)
		if self.name_order == "Groom & Bride":
			names = (self.groom_name, self.bride_name)
		self.couple_names = " & ".join(n for n in names if n)

		if self.start_date and self.end_date and self.end_date < self.start_date:
			frappe.throw(_("End date cannot be before start date"))
