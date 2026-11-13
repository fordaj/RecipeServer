"""Assemble the full HTML page shell for a rendered recipe.

Holds the asset paths and the static markup fragments shared by every
recipe page. The fetch of the recipe-scaler markup happens once at
converter setup and is passed into ``build_recipe_html`` so rendering
performs no hidden file I/O.
"""

from html import escape
from textwrap import dedent

from ..color_utils import dark_mode_color
from .icons import ASSETS_DIR, NOTEBOOK_SVG, PENCIL_SVG, icon_html

RECIPE_SCALER_HTML = ASSETS_DIR / "recipe-scaler.html"

CSS_PATH = "/assets/style.css"
DEFINITIONS_CSS_PATH = "/assets/definitions.css"
BASE_CSS_PATH = "/assets/base.css"
DIALOG_SHELL_CSS_PATH = "/assets/dialog-shell.css"
DIALOGS_JS_PATH = "/assets/dialogs.js"
RECIPE_JS = "/assets/recipe.js"
RECIPE_SCALER_CSS = "/assets/recipe-scaler.css"
RECIPE_EDITOR_JS = "/assets/recipe-editor/recipe-editor.js"
FIELDS_JS = "/assets/recipe-editor/fields.js"
RECIPE_EDITOR_CSS = "/assets/recipe-editor/recipe-editor.css"
METADATA_PICKER_JS = "/assets/recipe-editor/metadata-picker.js"
AI_PROGRESS_JS = "/assets/recipe-editor/ai-progress.js"
RECIPE_SCALER_JS = "/assets/recipe-scaler.js"
FEEDBACK_CSS = "/assets/feedback.css"
COMMENTS_JS = "/assets/comments.js"
PULL_DOWN_PAGE_REFRESH_CSS = "/assets/pull-down-page-refresh.css"
RATINGS_JS = "/assets/ratings.js"
RECIPE_FEEDBACK_JS = "/assets/recipe-feedback.js"
TIME_JS = "/assets/time.js"
ICONS_JS = "/assets/icons.js"
PULL_DOWN_PAGE_REFRESH_JS = "/assets/pull-down-page-refresh.js"
LOGO_SVG = "/assets/logo.svg"

KATEX = """
<link rel="stylesheet" href="/assets/katex/dist/katex.min.css">
<script defer src="/assets/katex/dist/katex.min.js"></script>
<script defer src="/assets/katex/dist/contrib/auto-render.min.js"></script>
<script defer src="/assets/katex-init.js"></script>
"""

HOME_PAGE_ICON_HTML = f"""
<a href="/index.html" class="recipe-home">
    {icon_html(NOTEBOOK_SVG, "recipe-icon")}
</a>
"""

EDIT_RECIPE_HTML = f"""
<button id="edit-recipe"class="recipe-home" type="button" aria-label="Edit recipe" title="Edit recipe">
    {icon_html(PENCIL_SVG, "recipe-icon")}
</button>
"""


def doc_specific_overrides(heading_color: str) -> str:
    """Return the per-page CSS that applies the recipe's accent color."""
    return dedent(f"""
        <style>
            :root {{
                --food-color: {heading_color};
            }}
            @media (prefers-color-scheme: dark) {{
                :root {{
                    --food-color: {dark_mode_color(heading_color)};
                }}
            }}

            .recipe-icon {{
                color: var(--food-color);
            }}
            h1, h2, h3, h4, h5, h6 {{
                color: var(--food-color);
            }}
        </style>
    """)


def build_recipe_html(
    *,
    source_title: str,
    heading_color: str,
    metadata_json: str,
    recipe_scaler_html: str,
    body: str,
    ratings_html: str,
    comments_html: str,
) -> str:
    """Render the full recipe page HTML shell."""
    return dedent(f"""<!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{escape(source_title)}</title>
        <link rel="icon" type="image/svg+xml" href="{LOGO_SVG}">
        <link rel="stylesheet" href="{DEFINITIONS_CSS_PATH}">
        <link rel="stylesheet" href="{BASE_CSS_PATH}">
        <link rel="stylesheet" href="{DIALOG_SHELL_CSS_PATH}">
        <link rel="stylesheet" href="{CSS_PATH}">
        <link rel="stylesheet" href="{RECIPE_SCALER_CSS}">
        <link rel="stylesheet" href="{RECIPE_EDITOR_CSS}">
        <link rel="stylesheet" href="{FEEDBACK_CSS}">
        <link rel="stylesheet" href="{PULL_DOWN_PAGE_REFRESH_CSS}">
        {doc_specific_overrides(heading_color)}
        {KATEX}
    </head>
    <body>
        <script id="recipe-metadata" type="application/json">{metadata_json}</script>
        <main class="recipe">
            <header class="recipe-header">
                {HOME_PAGE_ICON_HTML}
                {recipe_scaler_html}
                {EDIT_RECIPE_HTML}
            </header>
            {body}
            {ratings_html}
            {comments_html}
        </main>
        <script defer src="{TIME_JS}"></script>
        <script defer src="{ICONS_JS}"></script>
        <script defer src="{RECIPE_JS}"></script>
        <script defer src="{RECIPE_SCALER_JS}"></script>
        <script defer src="{PULL_DOWN_PAGE_REFRESH_JS}"></script>
        <script defer src="{RECIPE_FEEDBACK_JS}"></script>
        <script defer src="{COMMENTS_JS}"></script>
        <script defer src="{RATINGS_JS}"></script>
        <script defer src="{METADATA_PICKER_JS}"></script>
        <script defer src="{AI_PROGRESS_JS}"></script>
        <script defer src="{FIELDS_JS}"></script>
        <script defer src="{DIALOGS_JS_PATH}"></script>
        <script defer src="{RECIPE_EDITOR_JS}"></script>
    </body>
    </html>
    """)
