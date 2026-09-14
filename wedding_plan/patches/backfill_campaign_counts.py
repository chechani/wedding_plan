"""Fill in the new per-status counters on campaigns created before them.

The counters are only a cache of the recipient rows, so they can always be
rebuilt from those rows — which is exactly what this does.
"""
import frappe

from wedding_plan.whatsapp.scheduler import sync_campaign_counts


def execute():
	for name in frappe.get_all("WD WhatsApp Campaign", pluck="name"):
		sync_campaign_counts(name)
	frappe.db.commit()
