from frappe_psak_id.psak_id.report_lines import ensure_standard_report_lines


def execute():
	# Sites installed before 1.16.0 have no lines of the statement of changes in equity
	ensure_standard_report_lines()
