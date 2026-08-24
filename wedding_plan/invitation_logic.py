"""
Shared, centralized rules for the Invitations & Manvaar module — status
lifecycle, valid transitions, and the "Fully Invited" definition. Kept out of
the DocType controllers and out of api/invitations.py so both can import the
same rules instead of re-implementing them (and so the frontend never has to
re-derive "fully invited" itself).

Status model: "Redo" is deliberately NOT a separate status. It's a flag
(WD Invitation Task.retry_required / retry_count) attached to the Failed
status — a household is either in Failed or it isn't; "redo" describes what
happens next (Failed -> Planned), not a state of its own. This keeps the
status list to the six values the frontend already renders and avoids a
second axis of truth to keep in sync.
"""
import frappe
from frappe import _

STATUSES = ["Not Required", "Planned", "Sent", "Delivered", "Acknowledged", "Failed"]

# Relative order for "forward progress" comparisons. Failed is intentionally
# not part of the line — it's reachable from any in-progress status and only
# ever resolves back to Planned (redo) or Not Required (cancel).
_ORDER = {"Not Required": 0, "Planned": 1, "Sent": 2, "Delivered": 3, "Acknowledged": 4}

# Explicit allow-list of (from -> set of valid to). Forward skips are allowed
# (e.g. Not Required -> Delivered, for backfilling a channel that was already
# done before the tracker existed); moving backwards without going through
# Not Required or Failed first is not, since that would silently erase a
# recorded acknowledgement/delivery.
ALLOWED_TRANSITIONS = {
	"Not Required": {"Planned", "Sent", "Delivered", "Acknowledged", "Failed"},
	"Planned": {"Sent", "Delivered", "Acknowledged", "Failed", "Not Required"},
	"Sent": {"Delivered", "Acknowledged", "Failed", "Not Required"},
	"Delivered": {"Acknowledged", "Failed", "Not Required"},
	"Acknowledged": {"Not Required"},
	"Failed": {"Planned", "Not Required"},
}


def validate_transition(from_status, to_status):
	"""Raises if the move isn't allowed. No-op (same status) is always fine."""
	if from_status == to_status:
		return
	if from_status not in ALLOWED_TRANSITIONS or to_status not in STATUSES:
		frappe.throw(_("Unknown invitation status: {0}").format(to_status))
	if to_status not in ALLOWED_TRANSITIONS[from_status]:
		frappe.throw(
			_("Can't move an invitation task from {0} to {1} directly.").format(from_status, to_status)
		)


def is_forward_move(from_status, to_status):
	return _ORDER.get(to_status, -1) > _ORDER.get(from_status, -1)


def channel_terminal_statuses(acknowledgement_required):
	"""The status set that counts as 'done' for a channel."""
	if acknowledgement_required:
		return {"Acknowledged"}
	return {"Delivered", "Acknowledged"}


def is_task_complete(status, acknowledgement_required):
	if status == "Not Required":
		return False
	return status in channel_terminal_statuses(acknowledgement_required)
