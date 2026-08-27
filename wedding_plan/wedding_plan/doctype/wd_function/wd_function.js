// Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("WD Function", {
	setup(frm) {
		frm.set_query("sub_venue", () => ({
			filters: { venue: frm.doc.venue || "" },
		}));
	},
	venue(frm) {
		if (frm.doc.sub_venue) {
			frm.set_value("sub_venue", "");
		}
	},
});
