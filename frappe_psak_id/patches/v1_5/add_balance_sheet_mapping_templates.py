from frappe_psak_id.psak_id.mapping_templates import ensure_standard_mapping_templates


def execute():
	# Sites installed before 1.5.0 only have the profit or loss templates of version 1.0
	ensure_standard_mapping_templates()
