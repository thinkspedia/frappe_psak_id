from frappe_psak_id.permissions import grant_auditor_version_read, revoke_auditor_version_read
from frappe_psak_id.psak_id.mapping_templates import ensure_standard_mapping_templates
from frappe_psak_id.psak_id.report_lines import ensure_standard_report_lines


def after_install():
	ensure_standard_report_lines()
	# Templates link to report lines, so they come second
	ensure_standard_mapping_templates()


def after_sync():
	# The auditor role arrives with the fixtures, which Frappe syncs after after_install
	grant_auditor_version_read()


def before_uninstall():
	revoke_auditor_version_read()
