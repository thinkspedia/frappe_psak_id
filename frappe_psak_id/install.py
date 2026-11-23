from frappe_psak_id.psak_id.report_lines import ensure_standard_report_lines


def after_install():
	ensure_standard_report_lines()
