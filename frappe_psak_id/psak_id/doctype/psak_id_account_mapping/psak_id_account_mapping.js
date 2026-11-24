// Copyright (c) 2026, Thinkspedia and contributors
// For license information, please see license.txt

// The report lines an account of each root type is mapped to (same rule as the controller)
const LINE_FILTERS = {
	Income: { statement: "Profit or Loss" },
	Expense: { statement: "Profit or Loss" },
	Asset: { statement: "Financial Position", category: "Asset" },
	Liability: { statement: "Financial Position", category: "Liability" },
	Equity: { statement: "Financial Position", category: "Equity" },
};

frappe.ui.form.on("PSAK ID Account Mapping", {
	setup(frm) {
		frm.set_query("account", () => ({
			filters: { company: frm.doc.company, is_group: 0 },
		}));
		frm.set_query("report_line", () => ({
			filters: { line_type: "Line", disabled: 0, ...LINE_FILTERS[frm.doc.root_type] },
		}));
		frm.set_query("equity_component", () => ({
			filters: { line_type: "Line", disabled: 0, ...LINE_FILTERS.Equity },
		}));
		frm.set_query("oci_line", () => ({
			filters: { line_type: "Line", disabled: 0, statement: "Other Comprehensive Income" },
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
