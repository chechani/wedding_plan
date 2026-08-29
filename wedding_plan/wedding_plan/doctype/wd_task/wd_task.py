# Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import today

from wedding_plan.task_logic import enforce_polymorphic_assignment, resolve_contact_point

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

	def on_update(self):
		# Must run after the row is actually committed, not from validate():
		# the detail doctype's `task` field is a Link back to this document,
		# and Link validation checks the DB — during insert's validate(),
		# self.name is already assigned in memory but the row itself hasn't
		# been written yet, so that Link check fails against a task that
		# "doesn't exist" yet.
		#
		# Only worth re-checking when subtype could plausibly be new (this
		# doc was just created, or subtype itself just changed) — otherwise
		# every routine status/date edit on an existing task ran two
		# `frappe.db.exists` checks whose answer can't have changed since
		# last save.
		if self.is_new() or self.has_value_changed("subtype"):
			self._ensure_subtype_detail()

	def _ensure_subtype_detail(self):
		"""Picking a Sub-type is what 'grows the form' — instead of inlining
		10-30 fields here, auto-create the linked detail doctype (and clone
		its checklist template) the first time a subtype is set, so the
		task drawer can just link out to it. Never re-creates or deletes on
		a later subtype change — switching subtypes doesn't retroactively
		touch whatever detail data already exists."""
		if not self.subtype:
			return

		detail_doctype = frappe.db.get_value("WD Task Subtype", self.subtype, "detail_doctype")
		if not detail_doctype:
			return

		if not frappe.db.exists(detail_doctype, {"task": self.name}):
			frappe.get_doc({
				"doctype": detail_doctype,
				"task": self.name,
				"wedding": self.wedding,
			}).insert(ignore_permissions=True)

		if not frappe.db.exists("WD Task Checklist Item", {"task": self.name}):
			template_items = frappe.get_all(
				"WD Task Checklist Template Item",
				filters={"subtype": self.subtype},
				fields=["item"],
				order_by="sort_order asc",
			)
			for row in template_items:
				frappe.get_doc({
					"doctype": "WD Task Checklist Item",
					"task": self.name,
					"wedding": self.wedding,
					"item": row.item,
				}).insert(ignore_permissions=True)

	def _resolve_assignment(self):
		enforce_polymorphic_assignment(self, self.assigned_to_type, _ASSIGNMENT_FIELD, "this task's assignment")

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
