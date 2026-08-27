"""
Guest self-service portal — deliberately a narrow, explicit whitelisted API
surface rather than row-scoped Desk/REST access to WD Guest Member. The
existing tenant-isolation model in permissions.py is built for "many rows,
coarse role-based visibility" (any Wedding Member sees all of a wedding's
rows) — it's a poor fit for "this exact user sees exactly their own one row
and nothing else," which is what a guest needs. Every function below
resolves "which WD Guest Member am I" from frappe.session.user server-side
and touches only that member's own data.

Portal accounts are Website Users (no Desk access at all, unlike the System
Users auth.py.register() creates for planners) — a structural safety layer
independent of this module's own logic.

Kept entirely separate from wedding_plan/api/guests.py (planner-facing) —
different trust boundaries, don't mix them in one file.
"""
import frappe
from frappe import _
from frappe.auth import LoginManager
from frappe.utils import now_datetime, random_string
from frappe.utils.password import update_password

from wedding_plan.api.auth import _issue_token


def _guest_login_email(guest_member_name):
	# Internal-only Frappe User identifier — the guest never needs to know
	# this; they log in with their own mobile number or email (see
	# guest_login), which is resolved to this behind the scenes.
	return f"guest-{guest_member_name}@wedding-plan.guest"


def _my_guest_member():
	name = frappe.db.get_value("WD Guest Member", {"user": frappe.session.user, "portal_enabled": 1}, "name")
	if not name:
		frappe.throw(_("No guest portal profile found for this account."), frappe.PermissionError)
	return frappe.get_doc("WD Guest Member", name)


@frappe.whitelist()
def provision_guest_portal_user(guest_member):
	"""Planner-side. Requires normal write permission on WD Guest Member
	(effectively Accommodation/Guest Relations/Owner/Event Director, per
	ROLE_WRITE_REQUIREMENTS) — frappe.get_doc().save() below enforces this
	via the standard permission stack, same as any other doctype write."""
	doc = frappe.get_doc("WD Guest Member", guest_member)
	frappe.has_permission("WD Guest Member", ptype="write", doc=doc, throw=True)

	if not doc.portal_enabled:
		frappe.throw(_("Enable portal access for this guest member first."))
	if doc.user:
		frappe.throw(_("This guest member already has a portal user ({0}).").format(doc.user))
	if not (doc.mobile or doc.email):
		frappe.throw(_("Add a mobile number or email for this guest member before provisioning portal access."))

	login_email = _guest_login_email(doc.name)
	password = random_string(10)

	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": login_email,
			"first_name": doc.full_name,
			"user_type": "Website User",
			"send_welcome_email": 0,
			"enabled": 1,
		}
	).insert(ignore_permissions=True)
	update_password(user=user.name, pwd=password)

	doc.user = user.name
	doc.portal_invited_on = now_datetime()
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	return {
		"guest_member": doc.name,
		"login_identifier": doc.mobile or doc.email,
		"password": password,
	}


@frappe.whitelist(allow_guest=True)
def guest_login(identifier, password):
	"""Guest logs in with whatever they know — mobile or email — resolved
	server-side to the real internal User account. Rejects any Website User
	without a linked, portal_enabled WD Guest Member row, even if the
	underlying Frappe credentials are otherwise valid — defense in depth
	against this login path ever being reachable by an unrelated account."""
	guest_member_name = frappe.db.get_value(
		"WD Guest Member", {"mobile": identifier, "portal_enabled": 1}, "name"
	) or frappe.db.get_value("WD Guest Member", {"email": identifier, "portal_enabled": 1}, "name")
	if not guest_member_name:
		frappe.throw(_("Invalid credentials"))

	user = frappe.db.get_value("WD Guest Member", guest_member_name, "user")
	if not user:
		frappe.throw(_("Invalid credentials"))

	login_manager = LoginManager()
	login_manager.authenticate(user=user, pwd=password)
	login_manager.post_login()
	if not frappe.session.user or frappe.session.user == "Guest":
		frappe.throw(_("Invalid credentials"))

	frappe.db.set_value("WD Guest Member", guest_member_name, "portal_last_login", now_datetime())
	frappe.db.commit()
	return _issue_token(frappe.session.user)


@frappe.whitelist()
def get_my_profile():
	member = _my_guest_member()
	household = frappe.db.get_value(
		"WD Guest", member.guest, ["household_name", "category", "venue", "stay_required"], as_dict=True
	)
	return {
		"name": member.name,
		"full_name": member.full_name,
		"relation_to_household": member.relation_to_household,
		"mobile": member.mobile,
		"whatsapp_number": member.whatsapp_number,
		"email": member.email,
		"portal_access_level": member.portal_access_level,
		"household": household,
	}


@frappe.whitelist()
def get_my_functions():
	member = _my_guest_member()
	rows = frappe.get_all(
		"WD Guest Member Function",
		filters={"guest_member": member.name},
		fields=["function", "status", "meal_preference"],
	)
	function_types = {
		f.name: f.function_type
		for f in frappe.get_all("WD Function", filters={"name": ["in", [r.function for r in rows]]}, fields=["name", "function_type"])
	}
	return [{"function": r.function, "function_type": function_types.get(r.function), "status": r.status, "meal_preference": r.meal_preference} for r in rows]


@frappe.whitelist()
def update_my_contact_info(mobile=None, whatsapp_number=None, email=None):
	member = _my_guest_member()
	if mobile is not None:
		member.mobile = mobile
	if whatsapp_number is not None:
		member.whatsapp_number = whatsapp_number
	if email is not None:
		member.email = email
	member.save(ignore_permissions=True)
	return {"ok": True}


@frappe.whitelist()
def update_my_function_status(function, status):
	member = _my_guest_member()
	if member.portal_access_level != "Self Profile + RSVP":
		frappe.throw(_("RSVP is not enabled for this account."), frappe.PermissionError)
	if status not in ("Confirmed", "Declined"):
		frappe.throw(_("You may only confirm or decline."))

	row_name = frappe.db.get_value(
		"WD Guest Member Function", {"guest_member": member.name, "function": function}, "name"
	)
	if not row_name:
		frappe.throw(_("You are not listed for this function."))

	row = frappe.get_doc("WD Guest Member Function", row_name)
	row.status = status
	row.save(ignore_permissions=True)
	return {"ok": True, "status": row.status}


@frappe.whitelist(methods=["POST"])
def upload_my_document(field):
	if field not in ("photo", "aadhar_document"):
		frappe.throw(_("Invalid field."))
	member = _my_guest_member()

	if "file" not in frappe.request.files:
		frappe.throw(_("No file uploaded."))
	uploaded = frappe.request.files["file"]

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"attached_to_doctype": "WD Guest Member",
			"attached_to_name": member.name,
			"attached_to_field": field,
			"folder": "Home",
			"file_name": uploaded.filename,
			"content": uploaded.stream.read(),
			"is_private": 1,
		}
	)
	file_doc.save(ignore_permissions=True)

	member.set(field, file_doc.file_url)
	member.save(ignore_permissions=True)
	return {"ok": True, "file_url": file_doc.file_url}
