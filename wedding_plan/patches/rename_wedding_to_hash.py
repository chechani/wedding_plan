"""Wedding.name used to equal Wedding.slug (autoname: field:slug), which
made wedding URLs guessable (couple-names + year). Wedding now autonames on
a random hash; this one-time patch renames existing records to match.
frappe.rename_doc updates every Link("Wedding") field across the app's ~30
child doctypes automatically, so nothing else needs manual fixing up.

Safe to re-run: only touches rows where name == slug, which is exactly the
pre-migration state and never true again afterwards.
"""
import frappe
from frappe.model.rename_doc import rename_doc


def execute():
	weddings = frappe.get_all("Wedding", fields=["name", "slug"])
	for w in weddings:
		if w.name == w.slug:
			new_name = frappe.generate_hash(length=12)
			rename_doc("Wedding", w.name, new_name, force=True, ignore_permissions=True)
	frappe.db.commit()
