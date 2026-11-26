from frappe_psak_id.psak_id.mapping_templates import ensure_standard_mapping_templates


def execute():
	# Sites installed before 1.10.0 have no templates with cash flow lines (version 1.2)
	ensure_standard_mapping_templates()
