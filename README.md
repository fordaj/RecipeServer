# RecipeServer

Local recipe-site generator and HTTP server. It reads a tree of `recipe.md` files, renders each recipe to HTML, builds a searchable `index.html`, and serves the result at `http://localhost:8000`.

## Features

- Renders every `recipe.md` in the source tree to a recipe page and a searchable, sortable index.
- Scales quantities in inline code, generates hero images and accent colors, and typesets math with MathJax.
- Edits recipe Markdown, metadata, ratings, and comments in the browser, writing changes back to the source files.
- Shows metadata warnings for recipes missing recommended fields.
- Provides a system tray icon to open the recipes page, view server status, start or stop the server, and quit the app.
- Regenerates the affected recipe page and index whenever a recipe is saved.

## MathJax

Updated last on 10/23/2026 to latest version v4.1.3 using `pnpm install mathjax@4`
