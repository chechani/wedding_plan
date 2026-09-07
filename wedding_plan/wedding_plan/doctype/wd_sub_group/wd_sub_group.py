# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.model.naming import append_number_if_name_exists


class WDSubGroup(Document):
	def autoname(self):
		self._check_duplicate_within_wedding()
		# Human-readable id, e.g. "Friends" — but falls back to "Friends-1"
		# instead of failing outright the moment another wedding already has
		# a sub-group with the same label. `WD Sub Group` doc names are
		# global (one table across every wedding), while the label itself
		# is only meant to be unique *within* a wedding — two different
		# weddings, or the bride's and groom's side of the same one,
		# legitimately both have a "Friends" group (see the matching
		# comment in DistributionMatrix.tsx).
		self.name = append_number_if_name_exists(self.doctype, self.sub_group_name)

	def _check_duplicate_within_wedding(self):
		duplicate = frappe.db.exists(
			"WD Sub Group",
			{"wedding": self.wedding, "sub_group_name": self.sub_group_name},
		)
		if duplicate:
			frappe.throw(
				frappe._('A sub-group named "{0}" already exists for this wedding.').format(self.sub_group_name),
				frappe.DuplicateEntryError,
			)
