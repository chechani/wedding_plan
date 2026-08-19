"""
The Next.js frontend is a separately-hosted SPA/server, so cookie/session
auth is awkward (cross-origin cookies, CSRF tokens). Instead — same pattern
whatsform.in's own React frontend uses against frappe_whatsapp (see
`frappe_whatsapp.login.app_login` in AxiosInstance.tsx) — login/register
return a Frappe API key + secret the frontend stores and sends back as
`Authorization: token <api_key>:<api_secret>` on every request. That header
is Frappe's own standard token auth, so nothing else in the app needs to
know these tokens exist.

Note: logging in again rotates api_secret (a fresh one is issued each time,
the old one stops working), matching how a session token normally behaves —
don't expect two concurrently logged-in tabs to both keep working forever
after one of them logs in again.
"""
import frappe
from frappe.auth import LoginManager
from frappe.utils.password import update_password


def _issue_token(user: str) -> dict:
    user_doc = frappe.get_doc("User", user)
    api_key = user_doc.api_key or frappe.generate_hash(length=15)
    api_secret = frappe.generate_hash(length=15)
    user_doc.api_key = api_key
    user_doc.api_secret = api_secret
    user_doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {
        "email": user_doc.name,
        "full_name": user_doc.full_name,
        "api_key": api_key,
        "api_secret": api_secret,
    }


@frappe.whitelist(allow_guest=True)
def register(email, password, full_name):
    if frappe.db.exists("User", email):
        frappe.throw("An account with this email already exists")

    frappe.get_doc({
        "doctype": "User",
        "email": email,
        "first_name": full_name,
        "enabled": 1,
        "user_type": "System User",
        "send_welcome_email": 0,
    }).insert(ignore_permissions=True)

    update_password(user=email, pwd=password)
    return _issue_token(email)


@frappe.whitelist(allow_guest=True)
def login(email, password):
    login_manager = LoginManager()
    login_manager.authenticate(user=email, pwd=password)
    login_manager.post_login()
    if not frappe.session.user or frappe.session.user == "Guest":
        frappe.throw("Invalid credentials")
    return _issue_token(frappe.session.user)


@frappe.whitelist()
def me():
    user_doc = frappe.get_doc("User", frappe.session.user)
    return {"email": user_doc.name, "full_name": user_doc.full_name}
