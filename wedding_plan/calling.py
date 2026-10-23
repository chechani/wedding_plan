import frappe
import requests


def gen_response(status, message, data=None):
	frappe.response["status_code"] = status
	frappe.response["message"] = message
	frappe.response["data"] = data or {}


@frappe.whitelist()
def click_to_call(mobile_number):
	try:
		login_url = "https://connect.hipxpert.in/api/login"

		login_payload = {
			"user": "API_Sahaj",
			"password": "Sahaj123",
		}

		login_response = requests.post(login_url, data=login_payload)
		login_response.raise_for_status()

		login_data = login_response.json()
		access_token = login_data.get("access_token")

		if not access_token:
			frappe.log_error(
				frappe.as_json(login_data),
				"Login failed, no access token received",
			)
			return gen_response(401, "Login failed, no access token received")

		doc = frappe.db.get_list(
			"Extension",
			filters={"assign_to": frappe.session.user},
			fields=["name"],
			limit=1,
		)

		if not doc:
			return gen_response(404, "Extension not found for logged in user")

		extension = doc[0]["name"]

		url = "https://connect.hipxpert.in/api/manual-dial"
  
		# lead_id = frappe.db.get_value("WD Guest Member", {"mobile": mobile_number}, "name")
  
		payload = {
			"lead_id": "",
			"value": str(mobile_number)[-10:],
			"search": "YES",
			"preview": "NO",
			"focus": "YES",
			"agent_user": extension,
			"phone_code": "91",
		}

		headers = {
			"Accept": "application/json",
			"Authorization": f"Bearer {access_token}",
		}

		response = requests.post(url, headers=headers, data=payload)
		response.raise_for_status()

		response_data = response.json()

		if response_data.get("status"):
			return gen_response(
				200,
				response_data.get("message", "Call initiated successfully"),
				response_data,
			)
 
		return gen_response(
			400,
			response_data.get("message", "Failed to initiate call"),
			response_data,
		)

	except requests.exceptions.RequestException as e:
		frappe.log_error(frappe.get_traceback(), "Click to Call API Error")
		return gen_response(500, str(e))

	except Exception:
		frappe.log_error(frappe.get_traceback(), "Click to Call Error")
		return gen_response(500, "An error occurred while processing the request")
