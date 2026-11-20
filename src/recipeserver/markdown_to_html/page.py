"""Assemble the full HTML page shell for a rendered recipe.

Holds the asset paths and the static markup fragments shared by every
recipe page. The fetch of the recipe-scaler markup happens once at
converter setup and is passed into ``build_recipe_html`` so rendering
performs no hidden file I/O.
"""

from html import escape
from textwrap import dedent

from .._version import versioned_asset_url
from ..color_utils import dark_mode_color
from ..menu import MENU_CSS_URL, MENU_JS_URL, sandwich_menu_html
from .icons import ASSETS_DIR, NOTEBOOK_SVG, icon_html

RECIPE_SCALER_HTML = ASSETS_DIR / "recipe-scaler.html"

# Inline <script> snippet that registers the service worker (assets/sw.js)
# making /assets/* delivery resilient on flaky networks. Identical on
# recipe pages and the index; the worker's scope covers /assets/* only,
# so pages themselves stay network-fetched (no-store).
SW_REGISTRATION_SNIPPET = """    <script>
        if ("serviceWorker" in navigator) {
            navigator.serviceWorker.register("/assets/sw.js", { scope: "/assets/" }).catch(() => {});
        }
    </script>"""

CSS_PATH = "/assets/style.css"
DEFINITIONS_CSS_PATH = "/assets/definitions.css"
BASE_CSS_PATH = "/assets/base.css"
DIALOG_SHELL_CSS_PATH = "/assets/dialog-shell.css"
AI_ASSISTANT_CSS_PATH = "/assets/ai-assistant/ai-assistant.css"
DIALOGS_JS_PATH = "/assets/dialogs.js"
AI_ASSISTANT_JS_PATH = "/assets/ai-assistant/ai-assistant.js"
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
TIMELINE_JS = "/assets/recipe-history/timeline.js"
TIME_JS = "/assets/time.js"
ICONS_JS = "/assets/icons.js"
PULL_DOWN_PAGE_REFRESH_JS = "/assets/pull-down-page-refresh.js"
LOGO_SVG = "/assets/logo.svg"


def _katex(katex_css: str, katex_js: str, auto_render_js: str, katex_init_js: str) -> str:
    """Render the KaTeX loader block with content-hashed asset URLs."""
    return f"""
<link rel="stylesheet" href="{katex_css}">
<script defer src="{katex_js}"></script>
<script defer src="{auto_render_js}"></script>
<script defer src="{katex_init_js}"></script>
"""


HOME_PAGE_ICON_HTML = f"""
<a href="/index.html" class="recipe-home">
    {icon_html(NOTEBOOK_SVG, "recipe-icon")}
</a>
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


def _versioned_assets() -> dict[str, str]:
    """Content-hash every local asset the page references, keyed by template name."""
    return {
        name: versioned_asset_url(path)
        for name, path in {
            "logo_svg": LOGO_SVG,
            "definitions_css": DEFINITIONS_CSS_PATH,
            "base_css": BASE_CSS_PATH,
            "dialog_shell_css": DIALOG_SHELL_CSS_PATH,
            "ai_assistant_css": AI_ASSISTANT_CSS_PATH,
            "style_css": CSS_PATH,
            "recipe_scaler_css": RECIPE_SCALER_CSS,
            "recipe_editor_css": RECIPE_EDITOR_CSS,
            "feedback_css": FEEDBACK_CSS,
            "pull_down_page_refresh_css": PULL_DOWN_PAGE_REFRESH_CSS,
            "katex_css": "/assets/katex/dist/katex.min.css",
            "katex_js": "/assets/katex/dist/katex.min.js",
            "katex_auto_render_js": "/assets/katex/dist/contrib/auto-render.min.js",
            "katex_init_js": "/assets/katex-init.js",
            "time_js": TIME_JS,
            "icons_js": ICONS_JS,
            "recipe_js": RECIPE_JS,
            "recipe_scaler_js": RECIPE_SCALER_JS,
            "pull_down_page_refresh_js": PULL_DOWN_PAGE_REFRESH_JS,
            "recipe_feedback_js": RECIPE_FEEDBACK_JS,
            "timeline_js": TIMELINE_JS,
            "metadata_picker_js": METADATA_PICKER_JS,
            "comments_js": COMMENTS_JS,
            "ratings_js": RATINGS_JS,
            "ai_progress_js": AI_PROGRESS_JS,
            "fields_js": FIELDS_JS,
            "dialogs_js": DIALOGS_JS_PATH,
            "ai_assistant_js": AI_ASSISTANT_JS_PATH,
            "recipe_editor_js": RECIPE_EDITOR_JS,
        }.items()
    }


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
    assets = _versioned_assets()
    katex = _katex(assets["katex_css"], assets["katex_js"], assets["katex_auto_render_js"], assets["katex_init_js"])
    return dedent(f"""<!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, interactive-widget=resizes-content">
        <title>{escape(source_title)}</title>
        <link rel="icon" type="image/svg+xml" href="{assets["logo_svg"]}">
        <link rel="stylesheet" href="{assets["definitions_css"]}">
        <link rel="stylesheet" href="{assets["base_css"]}">
        <link rel="stylesheet" href="{assets["dialog_shell_css"]}">
        <link rel="stylesheet" href="{assets["ai_assistant_css"]}">
        <link rel="stylesheet" href="{MENU_CSS_URL}">
        <link rel="stylesheet" href="{assets["style_css"]}">
        <link rel="stylesheet" href="{assets["recipe_scaler_css"]}">
        <link rel="stylesheet" href="{assets["recipe_editor_css"]}">
        <link rel="stylesheet" href="{assets["feedback_css"]}">
        <link rel="stylesheet" href="{assets["pull_down_page_refresh_css"]}">
        {doc_specific_overrides(heading_color)}
        {katex}
        {SW_REGISTRATION_SNIPPET}
    </head>
    <body>
        <script id="recipe-metadata" type="application/json">{metadata_json}</script>
        <main class="recipe">
            <header class="recipe-header">
                {sandwich_menu_html(recipe_page=True)}
                {HOME_PAGE_ICON_HTML}
                {recipe_scaler_html}
            </header>
            {body}
            {ratings_html}
            {comments_html}
        </main>
        <script defer src="{MENU_JS_URL}"></script>
        <script defer src="{assets["time_js"]}"></script>
        <script defer src="{assets["icons_js"]}"></script>
        <script defer src="{assets["ai_assistant_js"]}"></script>
        <script defer src="{assets["recipe_js"]}"></script>
        <script defer src="{assets["recipe_scaler_js"]}"></script>
        <script defer src="{assets["pull_down_page_refresh_js"]}"></script>
        <script defer src="{assets["recipe_feedback_js"]}"></script>
        <script defer src="{assets["timeline_js"]}"></script>
        <script defer src="{assets["metadata_picker_js"]}"></script>
        <script defer src="{assets["comments_js"]}"></script>
        <script defer src="{assets["ratings_js"]}"></script>
        <script defer src="{assets["ai_progress_js"]}"></script>
        <script defer src="{assets["fields_js"]}"></script>
        <script defer src="{assets["dialogs_js"]}"></script>
        <script defer src="{assets["recipe_editor_js"]}"></script>
    </body>
    </html>
    """)
