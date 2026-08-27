// Copyright (c) 2026, Smarty Software Pvt Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("WD Task", {
	setup(frm) {
		frm.set_query("subtype", () => ({
			filters: { category: frm.doc.category || "" },
		}));
	},
	category(frm) {
		if (frm.doc.subtype) {
			frm.set_value("subtype", "");
		}
	},
});
