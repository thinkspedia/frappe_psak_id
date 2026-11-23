"""Differences between supported Frappe / ERPNext major versions live here, nowhere else.

PSAK ID supports v15 and v16 from one codebase. Code that must behave differently
per version imports a flag or helper from this module instead of checking
``frappe.__version__`` itself.
"""

import frappe

SUPPORTED_MAJORS = (15, 16)

FRAPPE_MAJOR = int(frappe.__version__.split(".")[0])


def is_supported() -> bool:
	return FRAPPE_MAJOR in SUPPORTED_MAJORS


#: Path the desk lives under: v16 moved it from /app to /desk (and redirects /app/* there)
DESK_PATH = "/desk" if FRAPPE_MAJOR >= 16 else "/app"
