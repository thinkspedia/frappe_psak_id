// Copyright (c) 2026, Thinkspedia and contributors
// For license information, please see license.txt

frappe.ui.form.on("PSAK ID Mapping Template", {
	setup(frm) {
		frm.set_query("report_line", "rows", (doc, cdt, cdn) => {
			const root_type = locals[cdt][cdn].root_type;
			const balance_sheet = ["Asset", "Liability", "Equity"].includes(root_type);
			return {
				filters: {
					line_type: "Line",
					disabled: 0,
					statement: balance_sheet ? "Financial Position" : "Profit or Loss",
					...(balance_sheet ? { category: root_type } : {}),
				},
			};
		});
		frm.set_query("oci_line", "rows", () => ({
			filters: { line_type: "Line", disabled: 0, statement: "Other Comprehensive Income" },
		}));
		// Opening cash, exchange effects and lines taken from another statement are computed
		const cash_flow_query = () => ({
			filters: {
				statement: "Cash Flow",
				line_type: "Line",
				disabled: 0,
				category: ["is", "set"],
				source_line: ["is", "not set"],
			},
		});
		frm.set_query("cash_flow_line", "rows", cash_flow_query);
		frm.set_query("cash_flow_line_decrease", "rows", cash_flow_query);
	},

	refresh(frm) {
		if (frm.is_new() || !frappe.model.can_create("PSAK ID Account Mapping")) return;
		frm.add_custom_button(__("Apply to Company"), () => apply_to_company(frm));
	},
});

function apply_to_company(frm) {
	const has_cash_flow_lines = frm.doc.rows.some((row) => row.cash_flow_line);
	const dialog = new frappe.ui.Dialog({
		title: __("Apply {0} to a Company", [frm.doc.name]),
		fields: [
			{
				fieldname: "company",
				label: __("Company"),
				fieldtype: "Link",
				options: "Company",
				reqd: 1,
				default: frappe.defaults.get_user_default("Company"),
				onchange: () => set_valid_from(dialog),
			},
			{
				fieldname: "valid_from",
				label: __("Valid From"),
				fieldtype: "Date",
				reqd: 1,
				description: __(
					"Usually the PSAK 118 adoption date of the company, or the day after its last final statement."
				),
			},
			{
				fieldname: "complete_cash_flow",
				label: __("Complete Cash Flow Lines"),
				fieldtype: "Check",
				default: has_cash_flow_lines ? 1 : 0,
				hidden: has_cash_flow_lines ? 0 : 1,
				description: __(
					"Mappings without a cash flow line get the line of the template from Valid From, in a new dated mapping; income and expenses outside operating profit that the template gives no line get the other cash flows of their activity. Statements before that date do not change."
				),
			},
			{
				fieldtype: "HTML",
				options: `<p class="text-muted small">${__(
					"Accounts that already have a mapping are skipped. Review the new mappings before preparing statements."
				)}</p>`,
			},
		],
		primary_action_label: __("Apply"),
		primary_action(values) {
			dialog.hide();
			frappe.call({
				method: "frappe_psak_id.psak_id.mapping.apply_template",
				args: { template: frm.doc.name, ...values },
				freeze: true,
				freeze_message: __("Creating mappings..."),
				callback: (r) => show_result(r.message, values.company),
			});
		},
	});
	dialog.show();
	set_valid_from(dialog);
}

function set_valid_from(dialog) {
	const company = dialog.get_value("company");
	if (!company) return;
	// Mappings in force in a final period are refused, so start after it
	frappe
		.call("frappe_psak_id.psak_id.mapping.default_valid_from", { company })
		.then(({ message }) => {
			if (message) dialog.set_value("valid_from", message);
		});
}

function show_result(result, company) {
	const list = (title, items) => {
		if (!items.length) return "";
		const rows = items
			.map((item) => {
				const text = typeof item === "string" ? item : `${item.account}: ${item.reason}`;
				return `<li>${frappe.utils.escape_html(text)}</li>`;
			})
			.join("");
		return `<details class="mt-2"><summary>${title} (${items.length})</summary><ul>${rows}</ul></details>`;
	};
	let summary = __(
		"{0} mappings created, {1} accounts skipped (already mapped), {2} not matched.",
		[result.created.length, result.skipped.length, result.unmatched.length]
	);
	if (result.completed.length) {
		summary +=
			" " + __("{0} mappings completed with a cash flow line.", [result.completed.length]);
	}
	const dialog = frappe.msgprint({
		title: __("Template Applied"),
		indicator: result.failed.length ? "orange" : "green",
		message:
			`<p>${summary}</p>` +
			list(__("Not matched: map these by hand"), result.unmatched) +
			list(
				__("Completed with a cash flow line"),
				result.completed.map((item) => `${item.account}: ${item.cash_flow_line}`)
			) +
			list(__("Refused"), result.failed) +
			list(__("Skipped"), result.skipped),
		primary_action: {
			label: __("Open Mapping Control"),
			action: () => {
				dialog.hide();
				frappe.set_route("query-report", "PSAK ID Mapping Control", { company });
			},
		},
	});
}
