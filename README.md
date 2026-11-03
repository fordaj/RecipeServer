# RecipeServer

RecipeServer turns a folder of Markdown recipes into a local recipe website and serves it in your browser. Each recipe becomes its own page, and everything is collected into a searchable, sortable index.

The app runs as a desktop process with a system tray icon. There is no database and no build pipeline: your Markdown files remain the source of truth, and edits made in the browser are written back to them.

## Features

- Renders every `recipe.md` in a source tree to a standalone recipe page.
- Builds a searchable, sortable `index.html` with ratings, meals, categories, difficulty, and last-edited information.
- Edits recipe Markdown, metadata, ratings, and comments in the browser.
- Writes browser edits back to the recipe's YAML front matter and Markdown body.
- Scales quantities inside inline code, such as `1 1/2 cups` or `1-2 tbsp`.
- Uses the first image in each recipe folder as the hero image and derives a page accent color from it.
- Shows metadata warnings for recipes missing recommended fields.
- Typesets math with a bundled copy of MathJax.
- Regenerates the affected recipe page and the index whenever a recipe is saved.
- Watches the recipe folder for external changes, so edits from other editors, new recipes, deleted recipes, and image changes appear without restarting.
- Refreshes open browser pages automatically when the library changes.
- Provides a tray icon to open the recipes page, refresh the library, view server status, start or stop the server, and quit.

## Supported platforms

| Platform | Status | Notes |
| --- | --- | --- |
| macOS | Supported | The tray runs on the main thread. |
| Windows | Supported | Includes `serve.bat`; the tray runs detached. |
| Linux | Untested | Requires Tk and an X11-compatible `pystray` backend. Wayland is not guaranteed to work. |

The app is a local desktop application, not a headless web service. A graphical session is required for the tray and the first-run folder picker.

## Requirements

- Python 3.14 or newer.
- [uv](https://docs.astral.sh/uv/) for dependency and virtual-environment management.
- Tk support in Python, used to choose the recipe folder on first launch.
- A desktop environment with system tray support.

## Installation

```bash
git clone https://github.com/fordaj/RecipeServer.git
cd RecipeServer
uv sync
```

`uv sync` creates the project virtual environment and installs runtime and development dependencies.

## Usage

Start the app from the repository root:

```bash
./serve.sh
```

On Windows, run `serve.bat`. The equivalent cross-platform command is:

```bash
uv run python -m recipeserver
```

On first launch, RecipeServer asks you to choose the directory that contains your recipes. The selected path is saved, the site is generated, and the server starts on `http://localhost:8000`.

Open the site in either of these ways:

- Click the tray icon and choose **Open Recipes**.
- Visit [http://localhost:8000](http://localhost:8000) directly.

The tray menu also shows the current server status and lets you start or stop the server. Use **Refresh Library** to force a full rebuild, and **Quit** to shut down the app. Closing the browser tab does not stop the server.

Pass `--log-level DEBUG` for more detailed output:

```bash
uv run python -m recipeserver --log-level DEBUG
```

## Live updates

RecipeServer watches the configured recipe directory while it runs. Changes made outside the browser are picked up automatically:

- Editing, adding, moving, or deleting a `recipe.md` updates the affected recipe page and the index.
- Adding, replacing, or deleting a recipe image updates the hero image, accent color, and copied files.
- Directory-level changes fall back to a full site rebuild.

Bursts of filesystem events are debounced, so saving a file once does not cause a rebuild storm. The app also ignores its own writes to avoid refreshing twice after a browser save.

Open recipe and index pages poll a lightweight revision endpoint and reload when the library changes. If the recipe editor is open with unsaved changes, the page does **not** reload. Instead, it shows a notice with **Reload page** and **Keep editing** actions, so unsaved work is never discarded silently.

If a change does not appear, choose **Refresh Library** from the tray. That performs a full regeneration without restarting the server.

## Recipe layout

Every directory containing a file named exactly `recipe.md` is treated as a recipe. Other Markdown files are ignored.

```text
my-recipes/
├── breakfast/
│   ├── recipe.md
│   └── pancakes.jpg
└── dinner/
    ├── recipe.md
    └── lemon-pasta.webp
```

The directory structure is preserved in the generated site. Images next to `recipe.md` are copied along with the page. The first image in filename-sorted order becomes that recipe's hero image and determines its accent color.

Supported image formats: JPG, JPEG, PNG, GIF, WebP, BMP, TIFF, TIF, SVG, and AVIF.

## Recipe format

Recipes use Markdown with optional YAML front matter:

```markdown
---
ratings:
  - name: Avery
    rating: 8
contributor: Avery
createdOn: "2026-02-14"
meals:
  - Dinner
categories:
  - Pasta
makes: 4
difficulty: 2
source:
  author: Example Cookbook
  title: Weeknight Pasta
  format: book
  url: ""
---

# Lemon Pasta

A quick weeknight dinner.

Mix `1 1/2 cups` flour with `1/2 tsp` salt.
```

The first `#` heading becomes the recipe and index title. If there is no heading, RecipeServer falls back to the front matter `title`, then to the directory name.

The metadata checker warns when these fields are missing:

- `ratings`
- `contributor`
- `createdOn`
- `meals`
- `categories`
- `makes`
- `difficulty`

Warnings are advisory. They appear in the hidden **Metadata Status** section of the index and do not block generation or saving.

`categories` is the canonical field. Older recipes using the singular `category` are still read correctly, but that field is normalized to `categories` when the recipe is saved.

### Quantity scaling

Wrap quantities in inline code to make them scalable:

```markdown
Add `1 cup` sugar and `1 1/2-2 1/2 tbsp` lemon juice.
```

RecipeServer recognizes common kitchen units and their aliases, including cups, tablespoons, teaspoons, grams, milliliters, liters, pounds, and ounces. It scales amounts but does not convert between units.

Unparseable inline-code quantities log a warning rather than breaking the page.

### Ratings, comments, and editing

The browser editor can update the recipe body and metadata. Ratings and comments are stored in the recipe's front matter as well.

A full editor save updates `updatedOn`. Rating and comment changes do not, so activity on those sections does not change the recipe's last-edited position in the index.

## Where files live

RecipeServer uses the operating system's application-data directory:

| Platform | Data directory |
| --- | --- |
| macOS | `~/Library/Application Support/recipe-server` |
| Windows | `%LOCALAPPDATA%\recipe-server` |
| Linux | `~/.local/share/recipe-server` |

Inside that directory:

- `config.txt` contains the path to the recipe source directory.
- `site/` contains the generated website.

The site directory is disposable. It is deleted and rebuilt every time RecipeServer starts and whenever a full fallback rebuild is needed. Never store source content or manual edits there.

To change the recipe source directory, update `config.txt` or remove it so the folder picker appears again.

Runtime logs are written under `.logs/` in the directory where the app was started.

## Troubleshooting

- **Port 8000 is unavailable:** RecipeServer always uses port 8000. Stop whatever else is using that port before launching it.
- **No tray icon appears:** Check that the app is running in a desktop session with tray support. On Linux, an X11-compatible `pystray` backend is required.
- **The folder picker does not appear:** Make sure the Python installation includes Tk.
- **A recipe is missing from the index:** Confirm that the file is named exactly `recipe.md` and lives under the configured recipe source directory.
- **A recipe has no hero image or expected accent color:** Add a supported image next to `recipe.md`. The first image in filename-sorted order wins.
- **Metadata warnings are visible:** Use the **Metadata Status** toggle in the index. Warnings are advisory and can be resolved by filling in the missing front matter fields.
- **External edits do not appear:** Wait a moment for the debounce window, then choose **Refresh Library** from the tray. Confirm that the changes are inside the configured recipe source directory and that the file is named exactly `recipe.md`.
- **A page shows “This recipe changed on disk”:** The editor has unsaved changes. Review them, then choose **Reload page** to load the version from disk or **Keep editing** to continue.

## Development

Run the test suite:

```bash
uv run pytest
```

Run a focused test file or test:

```bash
uv run pytest test/test_tray.py
uv run pytest test/test_ratings.py::test_validate_ratings_accepts_example_shape_and_decimal_score
```

### Project layout

```text
src/recipeserver/
├── __main__.py             # CLI entrypoint
├── core.py                 # startup, regeneration, parallel recipe conversion
├── file_watcher.py         # debounced source-tree monitoring
├── config.py               # recipe source configuration and folder picker
├── markdown_to_html.py     # recipe rendering and quantity scaling
├── index_html_generator.py # searchable/sortable index and metadata warnings
├── metadata_linter.py      # required-field list and warning text
├── image_handler.py        # supported images, hero selection, accent colors
├── server.py               # HTTP server and JSON APIs
├── tray.py                 # system tray icon and menu
└── assets/                 # CSS, JavaScript, icons, and vendored MathJax
test/                       # pytest suite
serve.sh / serve.bat        # launch helpers
```

### Architecture and invariants

- `recipe.md` files in the source tree are the source of truth. Generated HTML is disposable output.
- Every save re-renders that recipe page and rebuilds the index.
- The watcher refreshes only the recipes affected by external file and image changes, then rebuilds the index once per batch. Directory moves and unclassifiable changes use a full rebuild.
- The watcher ignores hidden files, editor swap files, temporary files, `.git`, and the generated site directory. It also records source signatures so a browser save does not trigger a second refresh.
- Each successful refresh increments a library revision. Pages poll `GET /api/revision` and reload when it changes.
- One broken recipe is skipped with a logged error so the rest of the site can still build.
- Metadata warnings are advisory and never block generation, serving, or saving.
- The HTTP API uses relative `.md` paths inside the configured source directory. Paths outside it are rejected.
- APIs include `GET /api/revision`, `GET /api/markdown`, `GET|POST /api/recipe-editor`, and `GET|POST /api/metadata/<field>`.
- Generated pages use root-absolute URLs such as `/assets/...`. They must be served from the site root; opening the HTML files directly will not load their assets.
- The server always uses port `8000`, binds to `0.0.0.0`, and has no authentication. Run it only on a trusted local network.
- There is no JavaScript build step. Frontend assets are served directly, and MathJax is vendored in `src/recipeserver/assets/mathjax`.

## MathJax

Updated last on 10/23/2026 to latest version v4.1.3 using `pnpm install mathjax@4`.
