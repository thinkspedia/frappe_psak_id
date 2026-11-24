app_name = "frappe_psak_id"
app_title = "PSAK ID"
app_publisher = "Thinkspedia"
app_description = "Indonesian financial statement presentation (PSAK 118) for ERPNext"
app_email = "helpdesk@thinkspedia.com"
app_license = "agpl-3.0"

# Apps
# ------------------

# The statements are built from ERPNext's General Ledger, Accounts and fiscal years
required_apps = ["erpnext"]

# Fixtures
# ------------------

fixtures = [
	# WHY: the four PSAK ID roles (Staff, Head, CFO, Auditor) gate every PSAK ID doctype and must
	# exist on install, before an administrator assigns them to users
	{"dt": "Role", "filters": [["name", "like", "PSAK ID - %"]]},
	# WHY: the review and approval workflow of PSAK ID Financial Statement (FR-08) is part of the
	# app, with its states and actions, so every site gets the same Draft to Final path
	{"dt": "Workflow", "filters": [["name", "=", "PSAK ID Financial Statement"]]},
	{
		"dt": "Workflow State",
		"filters": [
			["name", "in", ["Draft", "Under Review", "Approval CFO", "Final", "Reopened", "Cancelled"]]
		],
	},
	{
		"dt": "Workflow Action Master",
		"filters": [
			[
				"name",
				"in",
				["Submit for Review", "Return to Draft", "Send to CFO", "Approve", "Return to Review"],
			]
		],
	},
]

# No app_logo_url: the last installed app's value replaces the Desk navbar logo on every page,
# and PSAK ID is an add-on to ERPNext, not the site's brand. The apps screen tile below carries
# the logo instead.

# WHY: the apps screen tile is the one entry point to the PSAK 118 workspace (FR-11), shown with
# the app logo only to users who can open a PSAK ID statement or company policy. /app redirects
# to /desk on v16.
add_to_apps_screen = [
	{
		"name": "frappe_psak_id",
		"logo": "/assets/frappe_psak_id/images/psak-id-logo.svg",
		"title": "PSAK ID",
		"route": "/app/psak-118",
		"has_permission": "frappe_psak_id.permissions.has_app_permission",
	}
]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/frappe_psak_id/css/frappe_psak_id.css"
# app_include_js = "/assets/frappe_psak_id/js/frappe_psak_id.js"

# include js, css files in header of web template
# web_include_css = "/assets/frappe_psak_id/css/frappe_psak_id.css"
# web_include_js = "/assets/frappe_psak_id/js/frappe_psak_id.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "frappe_psak_id/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_kanban_js = {"doctype" : "public/js/doctype_kanban.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "frappe_psak_id/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "frappe_psak_id.utils.jinja_methods",
# 	"filters": "frappe_psak_id.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "frappe_psak_id.install.before_install"
# WHY: ship the standard PSAK 118 profit or loss lines once; later edits by the user are kept,
# so they are inserted on install instead of being synced as fixtures on every migrate
after_install = "frappe_psak_id.install.after_install"
# after_migrate = "frappe_psak_id.install.after_migrate"

# Uninstallation
# ------------

# before_uninstall = "frappe_psak_id.uninstall.before_uninstall"
# after_uninstall = "frappe_psak_id.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "frappe_psak_id.utils.before_app_install"
# after_app_install = "frappe_psak_id.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "frappe_psak_id.utils.before_app_uninstall"
# after_app_uninstall = "frappe_psak_id.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "frappe_psak_id.build.after_build"

# To hook into the build process of other apps
# The list of apps being built is passed as an argument

# after_app_build = "frappe_psak_id.build.after_app_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "frappe_psak_id.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["frappe_psak_id.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"frappe_psak_id.tasks.all"
# 	],
# 	"daily": [
# 		"frappe_psak_id.tasks.daily"
# 	],
# 	"hourly": [
# 		"frappe_psak_id.tasks.hourly"
# 	],
# 	"weekly": [
# 		"frappe_psak_id.tasks.weekly"
# 	],
# 	"monthly": [
# 		"frappe_psak_id.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "frappe_psak_id.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "frappe_psak_id.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "frappe_psak_id.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "frappe_psak_id.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["frappe_psak_id.utils.before_request"]
# after_request = ["frappe_psak_id.utils.after_request"]

# Job Events
# ----------
# before_job = ["frappe_psak_id.utils.before_job"]
# after_job = ["frappe_psak_id.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"frappe_psak_id.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
