from collections import Counter

import frappe
from frappe.utils import add_to_date, now_datetime

from wedding_plan.whatsapp.whatsform_client import WasenderSessionError, send_wasender

# Statuses a recipient can sit in. Only "Pending" is picked up by the
# scheduler: a failure stays Failed on the record until someone explicitly
# retries it, so nothing is silently re-sent and nothing is silently lost.
SENDABLE = ("Pending",)
RETRYABLE = ("Failed", "Skipped", "Sending", "No Phone", "Session Expired")


def _update_invitation_task(wedding, household, **kwargs):
	"""Mirror the send onto the invitation matrix, best effort.

	The matrix refuses some transitions (a task already Acknowledged cannot go
	back to Failed, say). That must never change what the campaign recorded or
	stop the run: the WhatsApp attempt happened either way, and the recipient
	row is the record of it.
	"""
	# Imported inside the call: wedding_plan.api imports this module, so a
	# top-level import of an api submodule would be a cycle.
	from wedding_plan.api.invitations import update_invitation_task

	if not frappe.db.exists("WD Invitation Channel", "main"):
		return
	try:
		update_invitation_task(wedding, household, "main", **kwargs)
	except Exception:
		frappe.log_error(title="WhatsApp campaign: invitation task not updated", message=frappe.get_traceback())


def _next_account(wedding):
	accounts = frappe.get_all(
		"WD WhatsApp Account",
		filters={"wedding": wedding, "enabled": 1},
		fields=["name", "phone_number", "last_used_at"],
		order_by="last_used_at asc, creation asc",
		limit=1,
	)
	return frappe.get_doc("WD WhatsApp Account", accounts[0].name) if accounts else None


def _message_id(result):
	data = result.get("data") or {}
	# Never `result["message"]`: that is WasenderAPI's human-readable text
	# (a disconnected session reads "Your Whatsapp Session is not connected…"),
	# not an id.
	return result.get("message_id") or result.get("id") or data.get("msgId")


def personalize_message(message, household, guest_member=None):
	"""Fill the `{family}` and `{name}` placeholders.

	`household` is a WD Guest docname; its `household_name` is what
	`{family}` refers to. `{name}` is the individual guest's `full_name` on a
	Guest-audience campaign (`guest_member` set) and the household name on a
	family campaign, so one template reads naturally for either audience.
	A blank name (shouldn't happen, but data is data) falls back to "your
	family" / "there" rather than sending a literal empty string.
	"""
	if not message:
		return message
	family = (frappe.db.get_value("WD Guest", household, "household_name") or "your family").strip()
	person = family
	if guest_member:
		person = (frappe.db.get_value("WD Guest Member", guest_member, "full_name") or "there").strip()
	return message.replace("{family}", family).replace("{name}", person)


def campaign_counts(campaign_name):
	"""Per-status recipient counts, straight from the recipient rows.

	The rows are the record of truth — counters on the campaign are only a
	cache of this — so a retry, a re-send, or a crashed run can never leave
	the campaign claiming a different number than the families it lists.
	"""
	by_status = Counter(frappe.get_all(
		"WD WhatsApp Campaign Recipient",
		filters={"campaign": campaign_name},
		pluck="status",
		limit_page_length=0,
	))
	return {
		"total_count": sum(by_status.values()),
		"sent_count": by_status.get("Sent", 0),
		# A session that dropped mid-campaign is a family who did not get the
		# message, the same as any other failure.
		"failed_count": by_status.get("Failed", 0) + by_status.get("Session Expired", 0),
		"session_expired_count": by_status.get("Session Expired", 0),
		"skipped_count": by_status.get("Skipped", 0) + by_status.get("No Phone", 0),
		"pending_count": by_status.get("Pending", 0) + by_status.get("Sending", 0),
		# Left out on purpose (already got the message in another campaign);
		# never sent, never retried, and not a failure.
		"ignored_count": by_status.get("Ignored", 0),
		"by_status": dict(by_status),
	}


def sync_campaign_counts(campaign_name, **extra):
	counts = campaign_counts(campaign_name)
	frappe.db.set_value("WD WhatsApp Campaign", campaign_name, {
		"total_count": counts["total_count"],
		"sent_count": counts["sent_count"],
		"failed_count": counts["failed_count"],
		"skipped_count": counts["skipped_count"],
		"pending_count": counts["pending_count"],
		**extra,
	})
	return counts


def _advance_or_complete(campaign, **extra):
	"""Schedule the next send, unless this attempt was the last recipient
	still Pending — then finish the campaign right away.

	Without this, a campaign whose last family had just been sent (or had
	just failed) sat labelled "Running" with a next_send_at up to
	`interval_minutes` away, only turning "Completed" on the following
	scheduler tick that found nothing left to do. Checking here instead
	means the status reflects reality the moment the last attempt lands.
	"""
	remaining = frappe.db.count("WD WhatsApp Campaign Recipient", filters={"campaign": campaign.name, "status": ["in", SENDABLE]})
	if remaining:
		return sync_campaign_counts(campaign.name, status="Running", next_send_at=add_to_date(now_datetime(), minutes=campaign.interval_minutes or 10), **extra)
	return sync_campaign_counts(campaign.name, status="Completed", next_send_at=None, **extra)


def _record(row, status, reason=None, **fields):
	"""Write the outcome of one attempt onto the family's own row.

	`reason` is always set for anything that is not a clean Sent, so the
	planner never sees a bare "Failed" without being told why.
	"""
	row.status = status
	row.error = (reason or "")[:500] or None
	row.last_attempt_at = now_datetime()
	for field, value in fields.items():
		setattr(row, field, value)
	row.save(ignore_permissions=True)


def process_campaign(campaign_name):
	campaign = frappe.get_doc("WD WhatsApp Campaign", campaign_name)
	if campaign.status not in ("Scheduled", "Running"):
		return {"processed": False, "status": campaign.status}
	if campaign.next_send_at and campaign.next_send_at > now_datetime():
		return {"processed": False}

	recipient = frappe.get_all(
		"WD WhatsApp Campaign Recipient",
		filters={"campaign": campaign.name, "status": ["in", SENDABLE]},
		fields=["name"],
		order_by="creation asc",
		limit=1,
	)
	if not recipient:
		counts = sync_campaign_counts(campaign.name, status="Completed", next_send_at=None)
		return {"processed": False, "completed": True, "counts": counts}

	row = frappe.get_doc("WD WhatsApp Campaign Recipient", recipient[0].name)
	account = _next_account(campaign.wedding)
	if not account:
		reason = "No enabled WhatsApp sender account is configured."
		sync_campaign_counts(campaign.name, status="Failed", last_error=reason)
		return {"processed": False, "error": reason}

	row.attempts = (row.attempts or 0) + 1
	_record(row, "Sending", None, account=account.name)
	message = personalize_message(campaign.message, row.household, row.guest_member)
	# The invitation matrix is per household. One guest getting (or missing)
	# a message says nothing about whether the family was invited, so only
	# family campaigns move it.
	mirror_to_matrix = not row.guest_member
	try:
		attachment_path = None
		if campaign.media_file:
			attachment_path = frappe.get_doc("File", {"file_url": campaign.media_file}).get_full_path()
		result = send_wasender(account, row.phone, message, attachment_path=attachment_path)
		message_id = _message_id(result)
		_record(row, "Sent", None, sent_at=now_datetime(), provider_message_id=message_id)
		frappe.db.set_value("WD WhatsApp Account", account.name, "last_used_at", now_datetime())
		frappe.get_doc({
			"doctype": "WD WhatsApp Message Log", "wedding": campaign.wedding, "direction": "Out",
			"to_phone": row.phone, "from_phone": account.phone_number, "payload": message,
			"status": "SENT", "provider_message_id": message_id,
		}).insert(ignore_permissions=True)
		_advance_or_complete(campaign, last_error=None)
		if mirror_to_matrix:
			_update_invitation_task(campaign.wedding, row.household, status="Sent", delivery_reference=message_id)
		return {"processed": True, "recipient": row.name, "status": row.status}
	except WasenderSessionError as error:
		# Every remaining family would hit the same disconnected session, one
		# interval apart. Pause instead: they stay Pending, and retrying (or
		# "Send next") once the account is reconnected picks the campaign up.
		reason = str(error)
		frappe.log_error(
			title=f"WhatsApp campaign paused, session not connected: {campaign.name}",
			message="\n".join([
				f"Campaign: {campaign.name} (wedding {campaign.wedding})",
				f"Recipient row: {row.name}, household {row.household}, guest {row.guest_member or '-'}, phone {row.phone}",
				f"Attempt: {row.attempts}, sender account: {account.name}",
				f"Reason: {reason}",
			]),
		)
		_record(row, "Session Expired", reason, provider_message_id=None)
		sync_campaign_counts(campaign.name, status="Paused", next_send_at=None, last_error=row.error)
		if mirror_to_matrix:
			_update_invitation_task(campaign.wedding, row.household, status="Failed", failure_reason=row.error)
		return {"processed": True, "recipient": row.name, "status": row.status, "error": row.error, "paused": True}
	except Exception as error:
		# The full traceback goes to the error log; the family's row keeps the
		# readable reason so it can be shown next to their name. For a provider
		# rejection that reason is WasenderAPI's own message (see
		# `WasenderError`), not a bare requests.HTTPError.
		reason = f"{type(error).__name__}: {error}" if not str(error).strip() else str(error)
		frappe.log_error(
			title=f"WhatsApp campaign send failed: {campaign.name}",
			message="\n".join([
				f"Campaign: {campaign.name} (wedding {campaign.wedding})",
				f"Recipient row: {row.name}, household {row.household}, guest {row.guest_member or '-'}, phone {row.phone}",
				f"Attempt: {row.attempts}, sender account: {account.name}",
				f"Attachment: {campaign.media_file or '<none>'}",
				f"Reason: {reason}",
				"",
				frappe.get_traceback(),
			]),
		)
		_record(row, "Failed", reason)
		_advance_or_complete(campaign, last_error=row.error)
		if mirror_to_matrix:
			_update_invitation_task(campaign.wedding, row.household, status="Failed", failure_reason=row.error)
		return {"processed": True, "recipient": row.name, "status": "Failed", "error": row.error}


def process_due_campaigns():
	for name in frappe.get_all(
		"WD WhatsApp Campaign",
		filters={"status": ["in", ["Scheduled", "Running"]], "next_send_at": ["<=", now_datetime()]},
		pluck="name",
		limit=100,
	):
		process_campaign(name)
	frappe.db.commit()
