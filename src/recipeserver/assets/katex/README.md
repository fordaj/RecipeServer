# KaTeX

Vendored browser build of [KaTeX](https://github.com/KaTeX/KaTeX) for typesetting math on recipe pages. The `dist/` directory is committed and served directly; there is no JavaScript build step in this repo.

## Version

KaTeX 0.19.1.

## How it got here

Downloaded with [pnpm](https://pnpm.io/) 11.17.0 (2026-11-08), following the same vendoring approach as the previous MathJax copy but for KaTeX:

```bash
# In a temporary directory (outside this repo):
pnpm init
pnpm add katex

# Then vendor the browser build and license into RecipeServer:
cp -r node_modules/katex/dist src/recipeserver/assets/katex/dist
cp node_modules/katex/LICENSE src/recipeserver/assets/katex/LICENSE
cp node_modules/katex/package.json src/recipeserver/assets/katex/package.json
```

Only the published browser build under `dist/` is vendored — `src/`, `types/`, `katex.ts`, `cli.js`, and `node_modules/` from the npm package are not committed. `LICENSE` and `package.json` are kept for provenance (KaTeX is MIT-licensed; see `LICENSE`).

Because the repo `.gitignore` ignores `dist/` directories, `src/recipeserver/assets/katex/dist/` is explicitly un-ignored there.

## How it is used

Recipe pages load `dist/katex.min.css`, `dist/katex.min.js`, and `dist/contrib/auto-render.min.js` (see `KATEX` in `markdown_to_html.py`). `src/recipeserver/assets/katex-init.js` auto-renders `\( ... \)` and `\[ ... \]` emitted by `pymdownx.arithmatex`, ignoring `.quantity` elements, which are rendered directly with `katex.render` in `recipe-scaler.js`.

## Updating

To update, repeat the pnpm download in a temporary directory and replace `dist/`, `LICENSE`, and `package.json` here. Update the version in the repo `README.md` accordingly.
