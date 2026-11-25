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
	},

	refresh(frm) {
		if (frm.is_new() || !frappe.model.can_create("PSAK ID Account Mapping")) return;
		frm.add_custom_button(__("Apply to Company"), () => apply_to_company(frm));
	},
});

function apply_to_company(frm) {
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
				onchange: () => set_adoption_date(dialog),
			},
			{
				fieldname: "valid_from",
				label: __("Valid From"),
				fieldtype: "Date",
				reqd: 1,
				description: __("Usually the PSAK 118 adoption date of the company."),
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
	set_adoption_date(dialog);
}

function set_adoption_date(dialog) {
	const company = dialog.get_value("company");
	if (!company) return;
	frappe.db.get_value("PSAK ID Company Policy", company, "adoption_date").then(({ message }) => {
		if (message && message.adoption_date) {
			dialog.set_value("valid_from", message.adoption_date);
		}
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
	const summary = __(
		"{0} mappings created, {1} accounts skipped (already mapped), {2} not matched.",
		[result.created.length, result.skipped.length, result.unmatched.length]
	);
	const dialog = frappe.msgprint({
		title: __("Template Applied"),
		indicator: result.failed.length ? "orange" : "green",
		message:
			`<p>${summary}</p>` +
			list(__("Not matched: map these by hand"), result.unmatched) +
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
