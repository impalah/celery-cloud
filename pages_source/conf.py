# Configuration file for the Sphinx documentation builder.
#
# Build with `make docs` (sphinx-build -W --keep-going pages_source docs).
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys
import tomllib

sys.path.insert(0, os.path.abspath("../src"))

# -- Project information -----------------------------------------------------

project = "Celery Cloud"
copyright = "2025, impalah"
author = "impalah"

# The version is read from pyproject.toml so it never drifts
with open(os.path.abspath("../pyproject.toml"), "rb") as _pyproject:
    release = version = tomllib.load(_pyproject)["project"]["version"]

# -- General configuration ---------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinx.ext.napoleon",
    "sphinx.ext.githubpages",
    "sphinx.ext.intersphinx",
    "sphinx_copybutton",
    "sphinxcontrib.mermaid",
]

language = "en"
templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- AutoDoc configuration ---------------------------------------------------

autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
    "special-members": "__init__",
}
# The debug server needs the dev dependencies and is not part of the API
autodoc_mock_imports = ["fastapi", "uvicorn", "debugpy"]

# Napoleon: the code base uses Google style docstrings
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = False
napoleon_include_private_with_doc = False

intersphinx_mapping = {
    "python": ("https://docs.python.org/3/", None),
    "celery": ("https://docs.celeryq.dev/en/stable/", None),
}

# -- Options for HTML output -------------------------------------------------

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_baseurl = "/celery-cloud/"
html_title = f"Celery Cloud {release}"

html_theme_options = {
    "logo_only": False,
    "prev_next_buttons_location": "bottom",
    "style_external_links": False,
    "style_nav_header_background": "#2980B9",
    "collapse_navigation": True,
    "sticky_navigation": True,
    "navigation_depth": 4,
    "includehidden": True,
    "titles_only": False,
}
