from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from frappe.tests import UnitTestCase

from wedding_plan.whatsapp.whatsform_client import WasenderError, WasenderSessionError, send_wasender

SESSION_DOWN = {"message": "Your Whatsapp Session is not connected please connect your session first."}


def _account():
	return SimpleNamespace(name="Sender One", get_password=lambda field: "key")


def _reply(body):
	response = MagicMock(ok=True, status_code=200)
	response.json.return_value = body
	return response


class TestSendWasenderReply(UnitTestCase):
	def send(self, body):
		with patch("wedding_plan.whatsapp.whatsform_client.requests.post", return_value=_reply(body)):
			return send_wasender(_account(), "+971500000000", "hello")

	def test_disconnected_session_on_http_200_raises_session_error(self):
		with self.assertRaises(WasenderSessionError) as caught:
			self.send(SESSION_DOWN)
		self.assertIn("Sender One", str(caught.exception))

	def test_success_false_raises(self):
		with self.assertRaises(WasenderError) as caught:
			self.send({"success": False, "message": "Rate limited"})
		self.assertNotIsInstance(caught.exception, WasenderSessionError)

	def test_accepted_message_is_returned(self):
		body = {"success": True, "data": {"msgId": 123, "status": "in_progress"}}
		self.assertEqual(self.send(body), body)
