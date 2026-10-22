"""Relabel the sends that never happened because the WhatsApp session was down.

WasenderAPI answers a disconnected session with HTTP 200 and the message "Your
Whatsapp Session is not connected…", which used to be recorded as Sent with
that message stored as the provider id. Those rows become Session Expired
(retryable), the text moves to `error`, and the campaign counters are rebuilt.
"""
import frappe

from wedding_plan.whatsapp.scheduler import sync_campaign_counts

SESSION_TEXT = "%session%not connected%"


def execute():
	rows = frappe.get_all(
		"WD WhatsApp Campaign Recipient",
		filters={"status": "Sent", "provider_message_id": ["like", SESSION_TEXT]},
		fields=["name", "campaign", "account", "provider_message_id"],
		limit_page_length=0,
	)
	for row in rows:
		frappe.db.set_value("WD WhatsApp Campaign Recipient", row.name, {
			"status": "Session Expired",
			"error": f"WhatsApp session for sender account {row.account} is not connected: {row.provider_message_id}"[:500],
			"provider_message_id": None,
			"sent_at": None,
		}, update_modified=False)

	for log in frappe.get_all(
		"WD WhatsApp Message Log",
		filters={"status": "SENT", "provider_message_id": ["like", SESSION_TEXT]},
		pluck="name",
		limit_page_length=0,
	):
		frappe.db.set_value("WD WhatsApp Message Log", log, {"status": "SESSION_EXPIRED", "provider_message_id": None}, update_modified=False)

	for campaign in {row.campaign for row in rows}:
		sync_campaign_counts(campaign)
	frappe.db.commit()
