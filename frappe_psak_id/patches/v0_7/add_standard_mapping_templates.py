from frappe_psak_id.psak_id.mapping_templates import ensure_standard_mapping_templates


def execute():
	# Sites installed before 0.7.0 never ran the installer step that adds the templates
	ensure_standard_mapping_templates()
