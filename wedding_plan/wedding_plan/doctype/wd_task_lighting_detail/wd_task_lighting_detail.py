# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

from frappe import _
from frappe.model.document import Document

from wedding_plan.doc_validation import assert_child_belongs_to_parent


class WDTaskLightingDetail(Document):
	def validate(self):
		assert_child_belongs_to_parent(
			"WD Task", self.task, "wedding", self.wedding,
			_("Task {0} does not belong to the selected Wedding.").format(self.task),
		)
