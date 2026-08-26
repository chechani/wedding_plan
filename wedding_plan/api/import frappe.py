import frappe
from frappe.auth import LoginManager


def gen_response(status, message, data=[]): 
	frappe.response["status_code"] = status
	frappe.response["message"] = message
	frappe.response["data"] = data


@frappe.whitelist(allow_guest=True)
def app_login(usr, pwd):

	if not usr:
		return "Username is required"
	if not pwd:
		return "Password is required"
	if not frappe.db.exists("User", usr):
		return "Invalid User"
	usage_doc = frappe.get_doc("Usage Info","Usage Info")
	expiry_date = usage_doc.plan_end_date
	if expiry_date and frappe.utils.nowdate() > expiry_date:
		return "Your subscription has expired. Please contact support to renew your subscription."
	login_manager = LoginManager()
	login_manager.authenticate(usr, pwd)
	login_manager.post_login()
	backend_url = f"https://{frappe.local.request.host}"
	if frappe.response["message"] == "Logged In":
		user = login_manager.user
		frappe.response["key_details"] = generate_key(user)
		frappe.response["user_details"] = get_user_details(user)
		frappe.response["role_details"] = get_user_role_details(user)
	else:
		return False


def get_user_role_details(user):
	role_details = frappe.get_all(
		"User",
		filters={"name": user},
		fields=[
			"name",
			"first_name",
			"last_name",
			"email",
			"mobile_no",
			"gender",
			"role_profile_name",
		],
	)

	for row in role_details:
		user_doc = frappe.get_doc("User", row.name)
		roles = []
		for roles_row in sorted(user_doc.roles, key=lambda x: x.role):
			roles.append({"role": roles_row.role})
		row["roles"] = roles

	if role_details:
		return roles


def generate_key(user):
	user_details = frappe.get_doc("User", user)
	api_secret = api_key = ""
	if not user_details.api_key and not user_details.api_secret:
		api_secret = frappe.generate_hash(length=15)
		api_key = frappe.generate_hash(length=15)
		user_details.api_key = api_key
		user_details.api_secret = api_secret
		user_details.save(ignore_permissions=True)
	else:
		api_secret = user_details.get_password("api_secret")
		api_key = user_details.get("api_key")
	return {
		"api_secret": api_secret,
		"api_key": api_key,
		"auth_token": f"token {api_key}:{api_secret}",
	}


def get_user_details(user):
	user_details = frappe.get_all(
		"User",
		filters={"name": user},
		fields=[
			"name",
			"first_name",
			"last_name",
			"email",
			"mobile_no",
			"gender",
			"role_profile_name",
		],
	)
	if user_details:
		return user_details