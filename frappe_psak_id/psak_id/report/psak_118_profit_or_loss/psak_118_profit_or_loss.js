// Copyright (c) 2026, Thinkspedia and contributors
// For license information, please see license.txt

const PSAK_118_PL = "PSAK 118 Profit or Loss";

frappe.query_reports[PSAK_118_PL] = {
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
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(
				frappe.datetime.add_months(frappe.datetime.get_today(), -1)
			),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_end(
				frappe.datetime.add_months(frappe.datetime.get_today(), -1)
			),
			reqd: 1,
		},
		{
			fieldname: "periodicity",
			label: __("Periodicity"),
			fieldtype: "Select",
			options: [
				{ value: "Monthly", label: __("Monthly") },
				{ value: "Quarterly", label: __("Quarterly") },
				{ value: "Yearly", label: __("Yearly") },
			],
			default: "Monthly",
			reqd: 1,
		},
		{
			fieldname: "comparative",
			label: __("Comparative"),
			fieldtype: "Select",
			options: [
				{ value: "", label: __("None") },
				{ value: "Same Period Last Year", label: __("Same Period Last Year") },
				{ value: "Restated Prior Year", label: __("Prior Year, Restated") },
			],
		},
		{
			fieldname: "cost_center",
			label: __("Cost Center"),
			fieldtype: "Link",
			options: "Cost Center",
			get_query: () => ({
				filters: { company: frappe.query_report.get_filter_value("company") },
			}),
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

		const accounts = (data.accounts || {})[column.fieldname] || [];
		if (accounts.length && data.line_type === "Line") {
			text = `<a href="#" class="psak-gl-link" data-line="${frappe.utils.escape_html(
				data.line_code
			)}" data-column="${column.fieldname}" title="${__(
				"Open General Ledger"
			)}">${text}</a>`;
		}
		if (data.is_profit_or_loss) {
			return `<strong style="border-bottom: 3px double; padding-bottom: 1px">${text}</strong>`;
		}
		return strong ? `<strong>${text}</strong>` : text;
	},

	open_general_ledger(report, line_code, fieldname) {
		const row = (report.data || []).find((d) => d.line_code === line_code);
		const column = (report.raw_data.columns || []).find((c) => c.fieldname === fieldname);
		if (!row || !column) return;

		// The ledger shows every entry of these accounts; an account split between lines by a
		// conditional mapping therefore shows more than this line's amount
		const cost_center = report.get_filter_value("cost_center");
		frappe.route_options = {
			company: report.get_filter_value("company"),
			from_date: column.from_date,
			to_date: column.to_date,
			account: row.accounts[fieldname],
			cost_center: cost_center ? [cost_center] : [],
			finance_book: report.get_filter_value("finance_book") || "",
		};
		frappe.set_route("query-report", "General Ledger");
	},
};
