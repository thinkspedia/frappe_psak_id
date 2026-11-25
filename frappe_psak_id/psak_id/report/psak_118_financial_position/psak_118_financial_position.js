// Copyright (c) 2026, Thinkspedia and contributors
// For license information, please see license.txt

const PSAK_118_FP = "PSAK 118 Financial Position";

frappe.query_reports[PSAK_118_FP] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("Date"),
			fieldtype: "Date",
			// End of last month. frappe.datetime.month_end() ignores its argument.
			default: frappe.datetime.obj_to_str(moment().subtract(1, "month").endOf("month")),
			reqd: 1,
		},
		{
			fieldname: "comparative",
			label: __("Compare with Prior Year End"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "finance_book",
			label: __("Finance Book"),
			fieldtype: "Link",
			options: "Finance Book",
		},
		{
			fieldname: "unit",
			label: __("Unit"),
			fieldtype: "Select",
			options: [
				{ value: "", label: __("Company Default") },
				{ value: "Full", label: __("Full") },
				{ value: "Thousands", label: __("Thousands") },
				{ value: "Millions", label: __("Millions") },
			],
		},
		{
			fieldname: "language",
			label: __("Line Labels"),
			fieldtype: "Select",
			options: [
				{ value: "Both", label: __("Indonesian and English") },
				{ value: "Indonesian", label: __("Indonesian") },
				{ value: "English", label: __("English") },
			],
			default: "Both",
			reqd: 1,
		},
	],

	onload(report) {
		report.page.wrapper.on("click", "a.psak-gl-link", (event) => {
			event.preventDefault();
			const link = $(event.currentTarget);
			this.open_general_ledger(report, link.attr("data-line"), link.attr("data-column"));
		});
	},

	formatter(value, row, column, data, default_formatter) {
		if (!data) return default_formatter(value, row, column, data);
		const strong = data.line_type !== "Line";

		if (column.fieldname === "line") {
			let html = frappe.utils.escape_html(value || "");
			if (data.label_alt) {
				html += ` <em class="text-muted">${frappe.utils.escape_html(data.label_alt)}</em>`;
			}
			if (strong) html = `<strong>${html}</strong>`;
			return data.indented
				? `<span style="padding-inline-start: 1.25rem">${html}</span>`
				: html;
		}

		if (data.line_type === "Heading" || value === null || value === undefined) return "";

		// Statement style: negatives in brackets, zero as a dash
		let text = value === 0 ? "-" : format_number(Math.abs(value), null, 0);
		if (value < 0) text = `(${text})`;

		const ledger = (data.ledger || {})[column.fieldname];
		if (ledger && ledger.accounts.length && data.line_type === "Line") {
			text = `<a href="#" class="psak-gl-link" data-line="${frappe.utils.escape_html(
				data.line_code
			)}" data-column="${column.fieldname}" title="${__(
				"Open General Ledger"
			)}">${text}</a>`;
		}
		if (data.is_total) {
			return `<strong style="border-bottom: 3px double; padding-bottom: 1px">${text}</strong>`;
		}
		return strong ? `<strong>${text}</strong>` : text;
	},

	open_general_ledger(report, line_code, fieldname) {
		const row = (report.data || []).find((d) => d.line_code === line_code);
		const column = (report.raw_data.columns || []).find((c) => c.fieldname === fieldname);
		if (!row || !column) return;

		const ledger = row.ledger[fieldname];
		if (!ledger.exact && ledger.by_account.length) {
			// One set of General Ledger filters cannot select this line's entries; each account can
			this.choose_account(report, column, row.line, ledger.by_account);
			return;
		}
		this.route_to_general_ledger(
			report,
			column,
			ledger.accounts,
			ledger.filters,
			ledger.exact
		);
	},

	choose_account(report, column, line_label, by_account) {
		const dialog = new frappe.ui.Dialog({
			title: __("Open General Ledger: {0}", [line_label]),
			fields: [{ fieldname: "accounts", fieldtype: "HTML" }],
		});
		const rows = by_account
			.map(
				(item, index) => `<tr>
					<td><a href="#" data-index="${index}">${frappe.utils.escape_html(item.account)}</a></td>
					<td class="text-right">${format_number(item.amount, null, 0)}</td>
				</tr>`
			)
			.join("");
		dialog.fields_dict.accounts.$wrapper.html(
			`<p class="text-muted small">${__(
				"A conditional mapping splits an account of this line by cost center or project. Open the General Ledger for one account."
			)}</p><table class="table table-bordered table-sm"><tbody>${rows}</tbody></table>`
		);
		dialog.fields_dict.accounts.$wrapper.on("click", "a[data-index]", (event) => {
			event.preventDefault();
			const item = by_account[$(event.currentTarget).attr("data-index")];
			dialog.hide();
			this.route_to_general_ledger(report, column, [item.account], item.filters, item.exact);
		});
		dialog.show();
	},

	route_to_general_ledger(report, column, accounts, filters, exact) {
		frappe.route_options = {
			company: report.get_filter_value("company"),
			// From the start of the fiscal year: the General Ledger adds the opening balance
			from_date: column.from_date,
			to_date: column.to_date,
			account: accounts,
			// A conditional mapping splits an account between lines by cost center or project
			cost_center: filters.cost_center || [],
			project: filters.project || [],
			finance_book: report.get_filter_value("finance_book") || "",
		};
		if (!exact) {
			frappe.show_alert(
				{
					message: __(
						"The General Ledger shows only part of this line: other entries of these accounts are on other lines, or the line also holds the profit or loss of the year."
					),
					indicator: "orange",
				},
				10
			);
		}
		frappe.set_route("query-report", "General Ledger");
	},
};
