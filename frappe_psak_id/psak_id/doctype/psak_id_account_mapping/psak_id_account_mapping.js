// Copyright (c) 2026, Thinkspedia and contributors
// For license information, please see license.txt

frappe.ui.form.on("PSAK ID Account Mapping", {
	setup(frm) {
		frm.set_query("account", () => ({
			filters: {
				company: frm.doc.company,
				is_group: 0,
				root_type: ["in", ["Income", "Expense"]],
			},
		}));
		frm.set_query("report_line", () => ({
			filters: { line_type: "Line", statement: "Profit or Loss", disabled: 0 },
		}));
		frm.set_query("condition_value", () =>
			frm.doc.condition_type === "Cost Center"
				? { filters: { company: frm.doc.company, is_group: 0 } }
				: {}
		);
	},

	company(frm) {
		frm.set_value("account", null);
	},

	condition_type(frm) {
		frm.set_value("condition_value", null);
		const fixed = { "Cost Center": "Cost Center", Project: "Project" };
		frm.set_value("condition_doctype", fixed[frm.doc.condition_type] || null);
	},

	party_type(frm) {
		frm.set_value("condition_value", null);
		frm.set_value("condition_doctype", frm.doc.party_type || null);
	},

	async accounting_dimension(frm) {
		frm.set_value("condition_value", null);
		const { message } = frm.doc.accounting_dimension
			? await frappe.db.get_value(
					"Accounting Dimension",
					frm.doc.accounting_dimension,
					"document_type"
			  )
			: { message: {} };
		frm.set_value("condition_doctype", message.document_type || null);
	},
});
