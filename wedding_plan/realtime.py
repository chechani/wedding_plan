"""
Realtime propagation for Event Mode (implementation plan §14) — a minimal
invalidation ping, not a data push. When a doctype relevant to `/live`
changes, every *other* Wedding Member of the same wedding with an open
socket gets told "something changed, refetch" — not the changed data
itself. The existing `reload()` path (lib/event/useEventData.ts) already
knows how to refetch correctly; this only makes it fire sooner than the
next tab-refocus.

Targets each member's own **user room**
(`frappe.publish_realtime(..., user=...)`), not a custom "wedding:<name>"
room. Two reasons, both load-bearing:

  1. Frappe's client-side subscription protocol only supports
     `doctype_subscribe`/`doc_subscribe` (see `realtime/handlers.js` in the
     frappe app) — there is no event a client can emit to join an arbitrary
     custom room, so nothing would ever be listening on "wedding:<name>".
  2. `doctype_subscribe` joins a doctype-WIDE room with no tenant scoping
     (permission-checked once, at subscribe time, for the doctype only —
     not per row), so every connected client would receive an
     `{wedding, doctype, name}` payload for every OTHER wedding's pickups
     too. That leaks cross-tenant document existence/timing, which this
     app's row-level permission model (wedding_plan/permissions.py) exists
     specifically to prevent.

Every socket auto-joins its own `user:<user>` room on connect with no
subscribe step — see `frappe_handlers()` in the same file — so targeting
`Wedding Member.user` for this wedding is both the only mechanism that
actually has a listener, and is automatically as tenant-correct as every
other read in this app, since it is exactly the same membership list
`_wedding_query_condition` already checks.
"""
import frappe

EVENT_NAME = "wedding_plan:event_update"


def notify_event_update(doc, method=None):
	wedding = getattr(doc, "wedding", None)
	if not wedding:
		return
	users = frappe.get_all("Wedding Member", filters={"wedding": wedding}, pluck="user")
	if not users:
		return
	payload = {"wedding": wedding, "doctype": doc.doctype, "name": doc.name}
	for user in users:
		# after_commit=True: this hook runs inside validate/on_update, before
		# the transaction commits. Publishing immediately would tell another
		# tab to refetch something a rollback then undoes.
		frappe.publish_realtime(EVENT_NAME, payload, user=user, after_commit=True)
