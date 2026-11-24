from frappe_psak_id.permissions import grant_auditor_version_read


def execute():
	# Installed sites already have the auditor role; new installs get the rule in after_sync
	grant_auditor_version_read()
