// Copyright (c) 2026, Thinkspedia and contributors
// For license information, please see license.txt

const PSAK_MAPPING_CONTROL = "PSAK ID Mapping Control";
const PSAK_MAPPING = "PSAK ID Account Mapping";

frappe.query_reports[PSAK_MAPPING_CONTROL] = {
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
			fieldname: "finance_book",
			label: __("Finance Book"),
			fieldtype: "Link",
			options: "Finance Book",
		},
	],

	onload(report) {
		report.page.wrapper.on("click", "a.psak-fix", (event) => {
			event.preventDefault();
			const row = (report.data || [])[cint($(event.currentTarget).attr("data-row"))];
			if (row) this.fix(report, row);
		});
	},

	formatter(value, row, column, data, default_formatter) {
		if (!data) return default_formatter(value, row, column, data);
		if (column.fieldname === "severity_label") {
			const color = data.severity === "Blocking" ? "red" : "orange";
			return `<span class="indicator-pill ${color}">${frappe.utils.escape_html(
				value
			)}</span>`;
		}
		if (column.fieldname === "fix") {
			const label = this.fix_label(data);
			return label
				? `<a href="#" class="psak-fix" data-row="${cint(data.row_index)}">${label}</a>`
				: "";
		}
		return default_formatter(value, row, column, data);
	},

	fix_label(data) {
		return {
			"Not Mapped": __("Add Mapping"),
			"No Matching Condition": __("Add Fallback Mapping"),
			"Disabled Line": __("Open Mappings"),
			"Conflicting Mappings": __("Open Mappings"),
			"Other Items Above Threshold": __("Open Mappings"),
			"Difference to ERPNext": __("Open Profit and Loss"),
			"Restatement Difference": __("Open Profit and Loss"),
		}[data.check];
	},

	fix(report, data) {
		const company = report.get_filter_value("company");
		switch (data.check) {
			case "Not Mapped":
			case "No Matching Condition":
				frappe.new_doc(PSAK_MAPPING, { company, account: data.account });
				break;
			case "Disabled Line":
			case "Conflicting Mappings":
				frappe.set_route("List", PSAK_MAPPING, { company, account: data.account });
				break;
			case "Other Items Above Threshold":
				frappe.set_route("List", PSAK_MAPPING, { company, report_line: data.report_line });
				break;
			default:
				frappe.route_options = {
					company,
					filter_based_on: "Date Range",
					period_start_date: data.from_date,
					period_end_date: data.to_date,
					periodicity: "Yearly",
					finance_book: report.get_filter_value("finance_book") || "",
				};
				frappe.set_route("query-report", "Profit and Loss Statement");
		}
	},
};
