// Copyright (c) 2026, Thinkspedia and contributors
// For license information, please see license.txt

const STATEMENT_METHODS =
	"frappe_psak_id.psak_id.doctype.psak_id_financial_statement.psak_id_financial_statement";
const PRINT_METHODS = "frappe_psak_id.psak_id.print_statement";
const EXPORT_METHODS = "frappe_psak_id.psak_id.export_statement";
const PERIOD_MONTHS = { Monthly: 1, Quarterly: 3, Annual: 12 };
const RETURN_ACTIONS = ["Return to Draft", "Return to Review"];
const REOPEN_ROLES = ["PSAK ID - Accounting - Head", "PSAK ID - CFO"];

frappe.ui.form.on("PSAK ID Financial Statement", {
	refresh(frm) {
		// The workspace shortcut opens a new statement for every role; a reader such as the
		// auditor would land on an empty form they cannot save. Replacing the history entry
		// keeps Back from returning to it.
		if (frm.is_new() && !frappe.model.can_create(frm.doctype)) {
			frappe.route_flags.replace_route = true;
			frappe.set_route("List", frm.doctype);
			return;
		}

		// Lines come from Recompute; only their note numbers are edited by hand
		frm.set_df_property("lines", "cannot_add_rows", true);
		frm.set_df_property("lines", "cannot_delete_rows", true);
		show_check_results(frm);
		if (frm.is_new()) return;

		const editable = ["Draft", "Reopened"].includes(frm.doc.workflow_state);
		if (frm.doc.docstatus === 0 && editable && frm.perm[0].write) {
			frm.add_custom_button(__("Recompute"), () => recompute(frm));
		}
		if (frm.doc.docstatus === 1 && REOPEN_ROLES.some((role) => frappe.user.has_role(role))) {
			frm.add_custom_button(__("Reopen"), () => reopen(frm));
		}

		const filters = {
			company: frm.doc.company,
			from_date: frm.doc.from_date,
			to_date: frm.doc.to_date,
		};
		// An empty value would reach the report as the text "undefined" and fail its Link check
		if (frm.doc.finance_book) filters.finance_book = frm.doc.finance_book;
		frm.add_custom_button(
			__("Mapping Control"),
			() => frappe.set_route("query-report", "PSAK ID Mapping Control", filters),
			__("View")
		);
		frm.add_custom_button(
			__("PSAK 118 Profit or Loss"),
			() => frappe.set_route("query-report", "PSAK 118 Profit or Loss", filters),
			__("View")
		);
		const downloads = [
			[__("PDF"), `${PRINT_METHODS}.download_pdf`, {}],
			[__("Excel"), `${EXPORT_METHODS}.export_excel`, {}],
			[
				__("Structured Data (Excel)"),
				`${EXPORT_METHODS}.export_structured`,
				{ fmt: "xlsx" },
			],
			[__("Structured Data (CSV)"), `${EXPORT_METHODS}.export_structured`, { fmt: "csv" }],
		];
		for (const [label, method, args] of downloads) {
			frm.add_custom_button(label, () => download(frm, method, args), __("Download"));
		}
	},

	from_date(frm) {
		set_to_date(frm);
	},

	periodicity(frm) {
		set_to_date(frm);
	},

	before_workflow_action(frm) {
		if (!RETURN_ACTIONS.includes(frm.selected_workflow_action)) return;
		// Frappe freezes the page before this event; the dialog needs it unfrozen
		frappe.dom.unfreeze();
		return new Promise((resolve, reject) => {
			let sent = false;
			const dialog = new frappe.ui.Dialog({
				title: __(frm.selected_workflow_action),
				fields: [
					{
						fieldname: "reason",
						label: __("Reason"),
						fieldtype: "Small Text",
						reqd: 1,
						description: __("Tell the preparer what to change."),
					},
				],
				primary_action_label: __(frm.selected_workflow_action),
				primary_action({ reason }) {
					sent = true;
					dialog.hide();
					frappe
						.call(`${STATEMENT_METHODS}.set_return_reason`, {
							name: frm.doc.name,
							reason,
						})
						.then(() => {
							frappe.dom.freeze();
							resolve();
						}, reject);
				},
				on_hide() {
					if (!sent) reject();
				},
			});
			dialog.show();
		});
	},
});

function set_to_date(frm) {
	const months = PERIOD_MONTHS[frm.doc.periodicity];
	if (!frm.doc.from_date || !months) return;
	const last_month = frappe.datetime.add_months(frm.doc.from_date, months - 1);
	// frappe.datetime.month_end() ignores its argument and returns the end of the current month
	frm.set_value("to_date", frappe.datetime.obj_to_str(moment(last_month).endOf("month")));
}

function show_check_results(frm) {
	if (frm.is_new() || !frm.doc.computed_on) return;
	const escape = (text) => frappe.utils.escape_html(text).replace(/\n/g, "<br>");
	let message, color;
	if (frm.doc.blocking_issues) {
		message = `<div>${__("{0} checks fail. The statement cannot be sent for review.", [
			frm.doc.blocking_issues,
		])}</div><div class="small">${escape(frm.doc.check_messages || "")}</div>`;
		color = "red";
	} else if (frm.doc.other_items_warnings) {
		message = `<div>${__(
			"Checks pass. Other Items lines are above the threshold: explain them in Other Items Breakdown."
		)}</div><div class="small">${escape(frm.doc.other_items_warnings)}</div>`;
		color = "orange";
	} else {
		message = `<div>${__("All checks pass. Computed on {0}.", [
			frappe.datetime.str_to_user(frm.doc.computed_on),
		])}</div>`;
		color = "green";
	}
	// The preparer reads why the statement came back where they open it
	if (frm.doc.docstatus === 0 && frm.doc.return_reason) {
		message += `<div class="small">${__("Sent back: {0}", [
			escape(frm.doc.return_reason),
		])}</div>`;
	}
	frm.dashboard.set_headline_alert(message, color);
}

function recompute(frm) {
	frappe
		.call({
			method: `${STATEMENT_METHODS}.refresh_statement`,
			args: { name: frm.doc.name },
			freeze: true,
			freeze_message: __("Computing the statement from the General Ledger..."),
		})
		.then(() => frm.reload_doc());
}

function reopen(frm) {
	frappe.prompt(
		[
			{
				fieldname: "reason",
				label: __("Reason"),
				fieldtype: "Small Text",
				reqd: 1,
				description: __(
					"This version is cancelled and kept. A new version is created to correct, review and approve again."
				),
			},
		],
		({ reason }) =>
			frappe
				.call({
					method: `${STATEMENT_METHODS}.reopen_statement`,
					args: { name: frm.doc.name, reason },
					freeze: true,
				})
				.then(({ message }) => frappe.set_route("Form", frm.doctype, message)),
		__("Reopen {0}", [frm.doc.name]),
		__("Reopen")
	);
}

function download(frm, method, args) {
	const query = new URLSearchParams({ name: frm.doc.name, ...args });
	window.open(frappe.urllib.get_full_url(`/api/method/${method}?${query}`));
}
