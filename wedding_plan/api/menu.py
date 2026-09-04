"""
Menu execution: plain REST (/api/resource/WD Menu, /api/resource/WD Menu
Item as its child table) covers ordinary CRUD. This one bespoke method backs
the category-level "Mark all Starters Ready" bulk action — the whole point
of which is not clicking each item individually.
"""
import frappe


@frappe.whitelist()
def bulk_set_category_status(menu, category, status):
	"""Sets `status` on every item in `menu` belonging to `category`. Saves
	the parent (not ignore_permissions) so WD Menu's normal role gate
	(Catering Liaison/Venue Commander) applies exactly as it would to any
	other edit of this document."""
	doc = frappe.get_doc("WD Menu", menu)
	frappe.has_permission("Wedding", doc=doc.wedding, throw=True)

	updated = 0
	for item in doc.items:
		if item.category == category:
			item.status = status
			updated += 1

	doc.save()
	return {"updated": updated}
