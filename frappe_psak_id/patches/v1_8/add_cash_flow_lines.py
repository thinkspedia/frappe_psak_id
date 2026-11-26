from frappe_psak_id.psak_id.report_lines import ensure_standard_report_lines


def execute():
	# Sites installed before 1.8.0 have no cash flow lines
	ensure_standard_report_lines()
