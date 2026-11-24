from frappe_psak_id.psak_id.report_lines import ensure_standard_report_lines


def execute():
	# Sites installed before 1.1.0 only have the profit or loss lines
	ensure_standard_report_lines()
