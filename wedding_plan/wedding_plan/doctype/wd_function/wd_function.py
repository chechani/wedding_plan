# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class WDFunction(Document):
	def validate(self):
		self._check_sub_venue()

	def _check_sub_venue(self):
		if not self.sub_venue:
			return
		sub_venue = frappe.db.get_value("WD Sub Venue", self.sub_venue, "venue")
		if self.venue and sub_venue != self.venue:
			frappe.throw(_("Sub Venue {0} does not belong to the selected Venue.").format(self.sub_venue))
