// Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("WD Gifting", {
	setup(frm) {
		frm.set_query("guest_member", () => ({
			filters: { guest: frm.doc.guest || "" },
		}));
	},
	guest(frm) {
		if (frm.doc.guest_member) {
			frm.set_value("guest_member", "");
		}
	},
});
