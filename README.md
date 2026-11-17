# RecipeServer

```mermaid
flowchart LR
    md("<img src='barnacle:folder.svg' width='20' alt=''/><br/>my-recipes/<br/>recipe.md files") --> core("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>RecipeServer core<br/>regen()</u>")
    core --> site("<img src='barnacle:folder.svg' width='20' alt=''/><br/><u>site/<br/>static HTML</u>")
    site --> browser("<img src='barnacle:globe.svg' width='20' alt=''/><br/><u>Browser</u>")
    browser -->|"saves edits"| server("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>HTTP server<br/>/api/*</u>")
    server --> core
    tray("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>System tray</u>") --> core
    click core href "src/recipeserver/core.py.md"
    click site href "src/recipeserver/index_html_generator.py.md"
    click browser href "src/recipeserver/server.py.md"
    click server href "src/recipeserver/server.py.md"
    click tray href "src/recipeserver/tray.py.md"
    class md folder
    class core,server,tray goFile
    class site folder
    classDef folder fill:#f0c558,stroke:#8a6d1c,color:#332a05
    classDef goFile fill:#8fd8ef,stroke:#0277a8,color:#08303d
```

RecipeServer turns a folder of Markdown recipes into a local recipe website and serves it in your browser. Each recipe becomes its own page, and everything is collected into a searchable, sortable index.

The app runs as a desktop process with a system tray icon. There is no database and no build pipeline: your Markdown files remain the source of truth, and edits made in the browser are written back to them.

## Features

- Renders every `recipe.md` in a source tree to a standalone recipe page.
- Builds a searchable, sortable `index.html` with ratings, meals, categories, difficulty, and last-edited information.
- Dictates a search instead of asking for the keyboard, when the site is served over HTTPS.
- Serves the site over HTTPS for every address this machine has — locally trusted via a bundled [mkcert](https://github.com/FiloSottile/mkcert) certificate and [Caddy](https://github.com/caddyserver/caddy), with no configuration beyond one checkbox.
- Filters recipe ratings by reviewer (up to 30 reviewers, most active first) without hiding any recipe cards.
- Creates recipes from the index in an existing folder or a new folder.
- Optionally drafts recipes from pasted text or a URL with a local AI model, then fills the recipe editor for review.
- Floats a one-tap AI assistant on every page that answers general questions, edits the recipe on screen, and transcribes a long-press as a message when dictation is available.
- Uploads supported images directly into a recipe folder from the recipe editor.
- Edits recipe Markdown, metadata, ratings, and comments in the browser.
- Writes browser edits back to the recipe's YAML front matter and Markdown body.
- Scales quantities inside inline code, such as `1 1/2 cups` or `1-2 tbsp`.
- Combines the ingredients of the recipes selected in the index into a shopping list, with a scale control per recipe.
- Downloads the shopping list as Markdown, copies it to the clipboard, or prints it as a checklist.
- Uses the first image in each recipe folder as the hero image and derives a page accent color from it.
- Shows metadata warnings for recipes missing recommended fields.
- Typesets math with a bundled copy of KaTeX.
- Regenerates the affected recipe page and the index whenever a recipe is saved.
- Provides a tray icon to open the recipes page, view server status, start or stop the server, and quit.

## Supported platforms

| Platform | Status    | Notes                                                                                   |
| -------- | --------- | --------------------------------------------------------------------------------------- |
| macOS    | Supported | The tray runs on the main thread.                                                       |
| Windows  | Supported | Includes `serve.bat`; the tray runs detached.                                           |
| Linux    | Untested  | Requires Tk and an X11-compatible `pystray` backend. Wayland is not guaranteed to work. |

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
./scripts/serve.sh
```

On Windows, run `serve.bat`. The equivalent cross-platform command is:

```bash
uv run python -m recipeserver
```

On first launch, RecipeServer asks you to choose the directory that contains your recipes. The selected path is saved, the site is generated, and the server starts on `http://127.0.0.1:8000`.

Open the site in either of these ways:

- Click the tray icon and choose **Open Recipes**.
- Visit [http://127.0.0.1:8000](http://127.0.0.1:8000) directly.

The server listens on the loopback interface by default, so the site is not reachable from other machines. To serve it over HTTPS — which the dictation button requires — enable **HTTPS** in the Configuration dialog (see [Serving the site over HTTPS](#serving-the-site-over-https-optional)) or put a local reverse proxy or tunnel in front of it that terminates HTTPS. The proxy forwards to `http://127.0.0.1:8000` and sets `X-Forwarded-Proto: https`; that is what enables the dictation button (see below).

Use the **+** button in the index to create a recipe. Choose an existing folder or enter a new folder path relative to the configured recipe directory, then write the recipe in Markdown. The editor can also upload supported images beside the recipe; images added while editing an existing recipe are saved to that recipe's folder.

If a local AI model is configured, the create dialog also shows **From text**, **From URL**, and **From Images** inputs. Paste recipe text, a link, or choose one or more recipe photos and choose the matching **Generate** button; the model drafts the Markdown and metadata into the editor. Nothing is saved until you review the result and press **Create**.

The tray menu also shows the current server status and lets you start or stop the server. Use **Quit** to shut down the app. Closing the browser tab does not stop the server.

Pass `--log-level DEBUG` for more detailed output:

```bash
uv run python -m recipeserver --log-level DEBUG
```

## Optional local AI model

Recipe creation from text, URL, or image uses an [Ollama](https://ollama.com) server. Point RecipeServer at the Ollama base URL:

```toml
# In recipe-server-cfg.toml:
source_directory = "/path/to/recipes"
model_endpoint = "http://127.0.0.1:11434"
all_purpose_model_name = "llama3.2"
image_analysis_model = "llava3"
recipe_server_name = "My Recipe Server"
dictation_enabled = true
https_enabled = true
https_extra_names = ""
```

RecipeServer talks to Ollama's native API (`/api/chat`, `/api/ps`, and `/api/tags`). A configured endpoint that includes an OpenAI-style suffix such as `/v1` still works; the suffix is normalized away.

The TOML file lives in your user data directory (`recipe-server-cfg.toml`). Configuration can also be edited in the browser: choose **Configuration** from the menu on the home page, then Save and Cancel. Saving rebuilds the site immediately. If the `model_endpoint` key is absent, the app asks for the endpoint on startup:

```text
Ollama endpoint (for example http://127.0.0.1:11434). Press Enter to skip:
All-purpose model name (press Enter to auto-detect from the endpoint):
Image analysis model name (press Enter to auto-detect from the endpoint):
```

Press <kbd>Enter</kbd> at the endpoint prompt to skip the integration. The empty setting is saved, so the app will not ask again; to enable it later, add or edit the `model_endpoint` key in `recipe-server-cfg.toml` (or use the Configuration dialog). Set `all_purpose_model_name` (and `image_analysis_model` for From Images) when your server has more than one model, or leave it out and RecipeServer will ask `/api/tags` for the first available model.

The AI controls behave as follows:

- All controls are hidden when no model endpoint is configured.
- All controls are shown but disabled when the endpoint is configured but cannot be reached.
- The endpoint is checked with a short timeout each time the create dialog opens, so start the model server and reopen the dialog after it becomes available.
- Before generating, RecipeServer asks Ollama's `/api/ps` route whether the selected model is already loaded. When it is not, the dialog reports that the model is being loaded into memory.

While a recipe is generated, the dialog reports each step: checking the model, loading it into memory, preparing the source, thinking (when the model emits reasoning), generating, and complete or error. The generated Markdown is written to the recipe editor when generation finishes, and the final model load time, generation time, token count, and tokens per second are shown when Ollama reports them.

The model prompt requirements are read from `src/recipeserver/NewRecipePrompt.md` on every app run, so edits to that file take effect the next time you start RecipeServer. For **From URL**, RecipeServer fetches the page and sends its readable text (not the raw HTML) to the model. For **From Images**, every chosen image is sent to the configured `image_analysis_model` with the prompt from `src/recipeserver/NewRecipeFromImagePrompt.md`, in the order the images were added; the transcriptions are concatenated and sent to the `all_purpose_model_name` model with `NewRecipePrompt.md` to draft the recipe. The generated Markdown and front matter only pre-fill the editor; review them before creating the recipe.

## The AI assistant

Every page carries a small circle in the bottom-right corner. It appears when the local AI endpoint is configured; on a phone it hides itself while you scroll down and comes back when you scroll up. Click it to open the chat panel — on a phone it pops out upper-left of the bubble, leaving the corner free for your thumb.

The assistant answers questions and edits the recipe on screen:

- General knowledge — "how many tablespoons are in a cup?"
- Questions about other recipes in the library — "what does the tomato soup do, step by step?"
- Edits to the recipe you are viewing — "adjust the recipe to use half as much salt" rewrites the recipe and regenerates the page; the chat then offers a Reload button.

When dictation is enabled and the page is served over HTTPS (the same conditions the search dictation button needs), the composer carries its own microphone inside the text box — and the bubble is also long-pressable. Press and hold either one and a microphone pops up directly above it (above the bubble, above the field) showing when the microphone is ready, listening, transcribing, done, or failed. Let go and the recording stops, is transcribed on this machine, and the transcript is sent to the assistant exactly as if you had typed and sent it. Tapping the inline microphone instead toggles recording on and off.

Boundaries are deliberate:

- The assistant can never delete a recipe, and it cannot edit any recipe other than the one you are viewing. There is no bulk edit — asking for one gets an explanation, not an edit.
- On the index page the assistant answers questions and looks recipes up, but there is no edit control: the edit tool is not offered, and a request for one is refused.
- Edits rewrite the recipe body wholesale but only change front matter through the editor's field rules; `updatedOn` is refreshed automatically. Ratings, comments, and any other front-matter fields are preserved.
- The conversation is kept only for the open page; reloading or navigating starts fresh.

The endpoint, the all-purpose model, and availability are the same settings the create dialog uses — if the create dialog shows the AI controls disabled, the assistant reports itself as unavailable instead of answering.

## Serving the site over HTTPS (optional)

Enabling the built-in HTTPS mode means any device can reach the site over a trusted, encrypted connection: phones, tablets, another computer, or Tailscale. It takes one checkbox.

In the app, open the home page's menu → **Configuration** → tick **HTTPS** → **Save**. Saving asks for one thing the very first time — the password to install the local CA (`mkcert -install`; one prompt, ever) — and from then on everything is automatic: the configured port (default `8000`) starts serving HTTPS instead of plain HTTP, the embedded server moves to an ephemeral loopback port behind [Caddy](https://github.com/caddyserver/caddy), and a certificate is issued for every address this machine answers to: its host name, its `.local` name, its IPv4/IPv6 addresses (LAN and Tailscale), and its Tailscale MagicDNS name. Extra names can be added with `https_extra_names` in `recipe-server-cfg.toml` if you reach the machine another way.

Opening the site from this machine needs nothing new — the tray's **Open Recipes** and `https://127.0.0.1:8000` just work (the local CA is now trusted by your browser).

To use HTTPS from **another device**, install the public root CA there once. Until you do, expect iOS Safari (and every other browser) to stop at a red **"This Connection Is Not Private"** screen — on iOS there is no "visit this site anyway" button for a certificate signed by an unknown local CA, so this step is not optional. The flow:

1. On that device, open `https://<any of this machine's addresses>:8000/rootCA.pem` (for example `https://maestro.local:8000/rootCA.pem` or your Tailscale address).
2. Install it as a CA certificate — on iOS: install the profile, then enable **Full Trust for Root Certificates** in Settings → General → About → Certificate Trust Settings; on Android: install a CA certificate from Settings → Security; on another computer: import it into the system trust store the same way `mkcert -install` does.
3. Reopen the same URL — the page loads without the warning. The profile alone is not enough on iOS; full trust must be enabled for that CA.

If a device shows a "name mismatch"-style error rather than "not private", you are reaching the machine at an address that is not in the certificate (for example a VPN interface the app could not see). Add it to `https_extra_names` in `recipe-server-cfg.toml` (or type it in the Configuration dialog), restart or Save, and the certificate gains that name.

The same checkbox turns HTTPS back off: the configured port returns to plain HTTP, and the embedded server takes it back.

Notes:

- The certificate is reissued automatically when the set of names changes (for example when a new network assigns a new LAN address) or when it nears expiry (mkcert leaf certificates are valid for 27 months; RecipeServer reissues 30 days ahead), so devices keep working without touching anything.
- The root CA private key (`mkcert -CAROOT`/`rootCA-key.pem`) never leaves this machine; only the public `rootCA.pem` is served.
- Don't run this next to [`tailscale serve`](https://tailscale.com/kb/1223/tailscale-serve) proxying the same port — they would both want it. Use one or the other: built-in HTTPS (above) or `tailscale serve --bg http://127.0.0.1:8000` with **HTTPS off**, which publishes `https://<machine>.<tailnet>.ts.net` with a real certificate and no CA install on the devices.
- Enabling HTTPS on a machine that already runs a reverse proxy on the same port will fail to start with a port-in-use error; stop the other process first.

## Dictating a search

The index has a microphone button next to the search field. Tap it, say what you are looking for, tap it again, and the transcript is typed into the search field — no keyboard needed, which is the point on a phone. You can also simply press and hold the button — release to stop — and a small status pill above it reports whether the microphone is ready, listening, transcribing, done, or failed.

The button is only offered when the site is served over HTTPS. Browsers hand out the microphone to secure pages only, so the button stays hidden on a plain `http://127.0.0.1:8000` page, and the server refuses transcription requests that did not arrive over HTTPS.

The easiest way to get HTTPS is the built-in mode: enable **HTTPS** in the Configuration dialog (see [Serving the site over HTTPS](#serving-the-site-over-https-optional)). Alternatively, run a local reverse proxy or tunnel in front of the app:

```bash
# Tailscale: serves https://<machine>.<tailnet>.ts.net and forwards to the app.
tailscale serve --bg http://127.0.0.1:8000
```

The proxy must forward to `http://127.0.0.1:8000` and set `X-Forwarded-Proto: https` (Caddy and Tailscale do this by default). Caddy and Cloudflare Tunnel work the same way.

The recording is transcribed on this machine with [whisper.cpp](https://github.com/ggml-org/whisper.cpp) through the `whisper-server` binary in the [fordaj/whisper-native](https://github.com/fordaj/whisper-native) release, bundled under `tools/whisper-native/`; no audio leaves the machine. The `base` model is used by default and its weights are downloaded from Hugging Face the first time a recording is transcribed, so the first dictation needs an internet connection and can take a minute or two. Set `RECIPE_SERVER_WHISPER_MODEL` to another model size (`tiny`, `base.en`, `small`, …) to trade accuracy for speed. RecipeServer manages the `whisper-server` process for you: it starts on the first transcription and stops when the app shuts down.

Dictation is on by default and can be switched off with the **Dictation** checkbox in the Configuration dialog (or the `dictation_enabled` key in `recipe-server-cfg.toml`). When it is off, no button is rendered, `POST /api/transcribe` answers 403, and no Whisper model is downloaded or loaded.

If the first dictation fails because the proxy gave up waiting for the model to download, raise the proxy's read timeout — nginx, for example, defaults to 60 seconds — or dictate again: the model stays loaded in memory after the first attempt.

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

When a reviewer is selected in **Filter Reviews**, Metadata Status also warns on recipes that have no rating from the selected reviewer(s).

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

| Platform | Data directory                                |
| -------- | --------------------------------------------- |
| macOS    | `~/Library/Application Support/recipe-server` |
| Windows  | `%LOCALAPPDATA%\recipe-server`                |
| Linux    | `~/.local/share/recipe-server`                |

Inside that directory:

- `recipe-server-cfg.toml` (TOML) holds the configuration: the `source_directory` path, the `recipe_server_name`, and optional `model_endpoint`, `all_purpose_model_name`, and `image_analysis_model` keys for the local AI integration. A legacy `config.txt` file is migrated automatically on startup.
- `site/` contains the generated website.

The site directory is disposable. It is deleted and rebuilt every time RecipeServer starts. Never store source content or manual edits there.

To change the recipe source directory, update the `source_directory` key in `recipe-server-cfg.toml` (or use **Configuration** on the home page), or remove the file so the folder picker appears again at startup.

Runtime logs are written under `.logs/` in the directory where the app was started.

## Troubleshooting

- **The configured port is unavailable:** RecipeServer listens on the port set in Configuration (default 8000). Either stop whatever else is using that port, or change `server_port` in `recipe-server-cfg.toml` (or use **Configuration**) and restart the app. When HTTPS is enabled, Caddy takes the configured port — a leftover `caddy` process from an unclean shutdown (e.g. after `kill -9`) keeps the port and blocks the next start; stop it with `pkill -f tools/caddy` (macOS/Linux) or Task Manager (Windows).
- **HTTPS fails to start with "Port 8000 is already in use; exiting":** Something else owns the configured port — possibly a stale `caddy` from a previous run (see above) or another reverse proxy or tunnel (including `tailscale serve`). Stop it, or disable **HTTPS** and use that setup instead.
- **HTTPS fails to start with "mkcert could not generate the certificate" or "Unable to install the mkcert local CA":** The bundled mkcert binary could not issue or install the local CA. On macOS the CA install needs your password (`sudo`); run `./scripts/serve.sh` from a terminal and try again, or run `mkcert -install` manually with sudo. On Windows, if the system store refuses the CA, run `mkcert -install` as Administrator (the bundled binary is `tools/mkcert/v*/windows-x86_64/mkcert.exe`).
- **HTTPS fails to start with "caddy did not become ready":** Check the log (`.logs/recipeserver.py.log`) for Caddy's own error lines. A port that looks free but is blocked by another process, or a certificate the filesystem cannot read, are the usual causes.
- **A device shows a certificate warning for the site:** That device does not trust the local CA yet (iOS Safari shows a red **"This Connection Is Not Private"** screen and offers no "visit anyway" button, so the CA must be installed and full trust enabled for it). Open `https://<any of this machine's addresses>:8000/rootCA.pem` from that device and install it as a CA certificate (on iOS also enable Full Trust for Root Certificates), or point the device at the literal IP with a warning bypass if you just want to look once.
- **The certificate expired or the machine's addresses changed:** Nothing to do — the certificate is reissued automatically when the SAN list changes or it nears expiry, on the next start or configuration save.
- **Switching HTTPS on or off in Configuration appears to fail:** The page's connection drops as the port switches schemes; the dialog navigates to the other scheme automatically. If the Configuration dialog reports an error instead, read the message — it names the failing step (certificate generation, CA install, or Caddy failing to bind the port).
- **No tray icon appears:** Check that the app is running in a desktop session with tray support. On Linux, an X11-compatible `pystray` backend is required.
- **The folder picker does not appear:** Make sure the Python installation includes Tk.
- **A recipe is missing from the index:** Confirm that the file is named exactly `recipe.md` and lives under the configured recipe source directory.
- **A recipe has no hero image or expected accent color:** Add a supported image next to `recipe.md`. The first image in filename-sorted order wins.
- **Metadata warnings are visible:** Use the **Metadata Status** toggle in the index. Warnings are advisory and can be resolved by filling in the missing front matter fields.
- **The From text, From URL, and From Images inputs are missing:** No local model endpoint is configured. Add `model_endpoint` to `recipe-server-cfg.toml` (or use **Configuration**), or remove that key and restart to be prompted again.
- **The From text, From URL, and From Images inputs are disabled:** The configured model endpoint could not be reached. Start the model server, check the endpoint URL, and reopen the create dialog.
- **The From Images input is disabled while text/URL work:** The image prompt could not be loaded. Check `src/recipeserver/NewRecipeFromImagePrompt.md` exists, and that the endpoint serves a vision-capable `image_analysis_model`.
- **AI generation fails with an HTTP error:** Confirm the Ollama server is running and reachable, and that it exposes `/api/chat` and `/api/ps`. Set `all_purpose_model_name` explicitly if auto-detection picks the wrong model.
- **The microphone button is missing from the search field:** The site is not being served over HTTPS. Enable **HTTPS** in the Configuration dialog (see [Serving the site over HTTPS](#serving-the-site-over-https-optional)), or put a local reverse proxy or tunnel in front of `http://127.0.0.1:8000` that sets `X-Forwarded-Proto: https`, and open the site through that address.
- **Dictation returns "Speech transcription requires an HTTPS connection":** The proxy forwarded the request without the `X-Forwarded-Proto` header (or with `http`). Configure the proxy to forward the original protocol.
- **Dictation returns "Nothing was heard. Try again.":** The model did not recognise anything in the recording. Speak closer to the microphone and hold the button a little longer.
- **Dictation returns "Dictation is disabled in the server configuration":** Dictation is switched off. Enable the **Dictation** checkbox in **Configuration** on the home page, or set `dictation_enabled = true` in `recipe-server-cfg.toml`.
- **Dictation fails with "whisper-server was not found":** The bundled binary is missing for this platform. Run `tools/whisper-native/update.sh` to download the release, or set `WHISPER_SERVER_BIN` to a `whisper-server` binary.
- **Dictation fails when the model cannot be downloaded:** The first transcription downloads the ggml weights from Hugging Face. Check the network connection, or download `ggml-base.bin` manually and place it in `<user-data>/recipe-server/models/`.
- **The first dictation takes a long time and the proxy times out:** The model weights are downloaded on the first transcription. Raise the proxy's read timeout (nginx defaults to 60 seconds) or dictate again — the model stays loaded after that.

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

### Browser end-to-end tests

`test/e2e/` contains Selenium browser tests that exercise the app as a real user
would: they build a site from a throwaway recipe tree, serve it from a live
RecipeServer on an ephemeral port, and drive a real browser against it. No user
data, configuration, or port 8000 is touched.

Prerequisites:

- Google Chrome (the default browser). Firefox and Edge also work via
  `RECIPE_SERVER_TEST_BROWSER`; see the environment variables below.
- The chromedriver matching your Chrome. Selenium Manager resolves it
  automatically on first run (needs network access once, cached afterwards).
  Override it with `RECIPE_SERVER_TEST_CHROMEDRIVER` if resolution fails.

Run only the browser tests:

```bash
uv run pytest test/e2e
```

Or the whole suite (which includes them):

```bash
uv run pytest
```

Skip the browser tests locally:

```bash
uv run pytest --ignore=test/e2e
```

Browser tests run headless by default. Relevant environment variables:

| Variable                                                               | Default           | Purpose                                                 |
| ---------------------------------------------------------------------- | ----------------- | ------------------------------------------------------- |
| `RECIPE_SERVER_TEST_BROWSER`                                           | `chrome`          | `chrome`, `firefox`, or `edge`.                         |
| `RECIPE_SERVER_TEST_HEADLESS`                                          | `1`               | Set to `0` to watch the browser.                        |
| `RECIPE_SERVER_TEST_CHROME_BINARY`                                     | auto              | Path to the Chrome/Chromium binary.                     |
| `RECIPE_SERVER_TEST_CHROMEDRIVER`                                      | auto              | Path to chromedriver.                                   |
| `RECIPE_SERVER_TEST_FIREFOX_BINARY` / `RECIPE_SERVER_TEST_EDGE_BINARY` | auto              | Path to the Firefox / Edge binary.                      |
| `RECIPE_SERVER_TEST_EDGEDRIVER`                                        | auto              | Path to edgedriver.                                     |
| `RECIPE_SERVER_TEST_ARTIFACTS`                                         | `.e2e-artifacts/` | Where failure screenshots and console logs are written. |

When a browser test fails, a screenshot and (Chrome/Edge) the browser console
log are saved to `.e2e-artifacts/` and attached to the pytest failure report;
CI uploads them as a workflow artifact. When the browser cannot be started the
tests fail in CI and skip locally (set `CI=true` to force the failure).

### Speech transcription tests

The dictation feature is covered by tests that need no model: `test/test_transcriber.py`
decodes real recordings (Opus in WebM, AAC in MP4, and WAV) with the installed
PyAV, `test/test_whisper_server.py` covers the subprocess lifecycle against a
stub server, and `test/test_speech_button.py` posts those recordings through the
`/api/transcribe` endpoint. The recorded phrase lives in `test/fixtures/speech/`.

The tests that run the real Whisper model are skipped by default, because they
download the model weights. Run them with:

```bash
RECIPE_SERVER_TEST_WHISPER=1 uv run pytest test/test_speech_model.py
```

| Variable                           | Default                            | Purpose                                                    |
| ---------------------------------- | ---------------------------------- | ---------------------------------------------------------- |
| `RECIPE_SERVER_TEST_WHISPER`       | unset                              | Set to `1` to run the tests that use the real model.       |
| `RECIPE_SERVER_TEST_WHISPER_MODEL` | `tiny`                             | Model size for those tests (`tiny`, `base`, `small`, …).   |
| `RECIPE_SERVER_WHISPER_MODEL`      | `base`                             | Model size the app uses.                                   |
| `RECIPE_SERVER_WHISPER_MODEL_DIR`  | `<user-data>/recipe-server/models` | Where the downloaded ggml weights are kept.                |
| `WHISPER_SERVER_BIN`               | bundled `tools/whisper-native/…`   | Points at the `whisper-server` binary to manage.           |
| `CADDY_BIN`                        | bundled `tools/caddy/…`            | Points at the `caddy` binary for the optional HTTPS mode.  |
| `MKCERT_BIN`                       | bundled `tools/mkcert/…`           | Points at the `mkcert` binary for the optional HTTPS mode. |
| `RECIPE_SERVER_HTTPS_DIR`          | `<user-data>/recipe-server/https`  | Where certificates, the Caddyfile, and markers are kept.   |

Writing new tests:

- Use the `recipe_server` fixture for a running server against temporary
  recipe/site directories and the `driver` fixture for the browser; request
  only the ones a test needs. `source_dir` is available separately when a test
  needs to inspect or mutate the recipe tree.
- Prefer `WebDriverWait`-based helpers from `test/e2e/helpers.py` over sleeps
  and prefer `data-testid` attributes (for example `[data-testid="recipe-item"]`)
  and stable element IDs over positional selectors.

Format Python (Black, line-length 150), Bash (shfmt), CSS/JS/HTML/Markdown/YAML (Prettier), TOML (taplo), and SVG (Prettier `--parser html`) via formattington (`uv run formattington all --config .formattington.json`, concurrently by default). Formatters are declared in `.formattington.json`; vendored KaTeX is excluded via `.prettierignore`. Requires `prettier` on PATH (`npm install -g prettier`) and `taplo` on PATH:

```bash
./scripts/format.sh
./scripts/format.sh --check
```

### Bundled tooling and CI

This repository carries compiled executables under `tools/` (pinned, platform-native; refreshed by each `tools/<name>/update.sh`) — mostly from the sibling `fordaj/*` repositories, plus the upstream [caddyserver/caddy](https://github.com/caddyserver/caddy) and [FiloSottile/mkcert](https://github.com/FiloSottile/mkcert) for the HTTPS mode:

| Tool                       | Used for                                                                                                   |
| -------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `tools/versioner`          | Compute `VERSION`/`TAG` for releases (`scripts/version.sh`, `scripts/release.sh`)                          |
| `tools/logamuffin`         | Shell logging behind `scripts/entry.sh` (`scripts/serve.sh`, `scripts/format.sh`, `scripts/release.sh`, …) |
| `tools/runner-spawner`     | Provision the self-hosted CI runners (`./scripts/spawn-runners.sh`)                                        |
| `tools/formattington-lite` | Formatting fallback; the pinned uv dependency is the primary path                                          |
| `tools/barnacle`           | Documentation site generation (`scripts/docs.sh`)                                                          |
| `tools/caddy`              | `caddy` binary fronting the optional HTTPS mode (all-interface TLS → the embedded server)                  |
| `tools/mkcert`             | `mkcert` binary issuing the locally-trusted certificate for the HTTPS mode                                 |

Scripts source `scripts/entry.sh`, which exposes `log()` backed by the
bundled logamuffin binary. Formatting is orchestrated by
[formattington](https://github.com/fordaj/formattington) both as a pinned
`uv` dev dependency (`./scripts/format.sh`) and as the committed config in
`.formattington.json`.

GitHub Actions (`.github/workflows/check-formatting.yml`, “PR Checks”) runs
on the self-hosted macOS and Windows runners provisioned above; it checks
formatting and runs the pytest suite — including the headless Selenium
browser tests — on every pull request. The browser tests run against the
system Chrome installed on each runner, with chromedriver resolved by
Selenium Manager. Releases are cut with `./scripts/release.sh`
(tag + GitHub release notes only — no binaries are published for this app).

### Project layout

```text
src/recipeserver/
├── __main__.py             # CLI entrypoint
├── core.py                 # startup, regeneration, parallel recipe conversion
├── config.py               # recipe source, local model settings, prompt loading
├── ai_recipe.py            # local-model status, URL fetching, recipe generation
├── markdown_to_html.py     # recipe rendering and quantity scaling
├── index_html_generator.py # searchable/sortable index and metadata warnings
├── shopping_list.py         # ingredient scraping for the shopping list
├── metadata_linter.py      # required-field list and warning text
├── image_handler.py        # supported images, hero selection, accent colors
├── server.py               # HTTP server and JSON APIs
├── https_setup.py          # optional HTTPS front-end: Caddy + mkcert, per-machine certificate
├── transcriber.py          # dictation: PyAV decode + whisper-server HTTP client
├── whisper_server.py       # whisper-server subprocess lifecycle and model download
├── tray.py                 # system tray icon and menu
├── NewRecipePrompt.md      # model prompt requirements, reloaded at startup
└── assets/                 # CSS, JavaScript, icons, and vendored KaTeX
test/                       # pytest suite (test/e2e/ holds the Selenium browser tests)
serve.bat / scripts/serve.sh      # launch helpers (Windows / Unix)
scripts/format.sh                   # Python (Black) and Bash (shfmt) formatting via formattington
scripts/spawn-runners.sh            # create the self-hosted CI runners (macOS/Windows)
scripts/                    # env cascade (entry.sh/env.sh) + version.sh + docs.sh
tools/                      # bundled binaries (fordaj/* and upstream caddyserver/caddy, FiloSottile/mkcert) + update.sh refreshers
```

### Architecture and invariants

- `recipe.md` files in the source tree are the source of truth. Generated HTML is disposable output.
- Every save re-renders that recipe page and rebuilds the index.
- One broken recipe is skipped with a logged error so the rest of the site can still build.
- Metadata warnings are advisory and never block generation, serving, or saving.
- The HTTP API uses relative `.md` paths inside the configured source directory. Paths outside it are rejected.
- APIs include `GET /api/recipe-folders`, `POST /api/recipe`, `GET /api/ai-status`, `POST /api/ai-recipe`, `GET /api/markdown`, `GET|POST /api/recipe-editor`, `GET|POST /api/metadata/<field>`, `GET /api/metadata-options`, `GET /api/shopping-list`, and `POST /api/transcribe`.
- `GET /api/metadata-options` returns the metadata values that are already used in the library (meals, categories, cuisine, tags, status, contributor, plus source author and title) with the number of recipes that use each of them, so the editor can offer them as dropdown options. The values are read from the recipe Markdown files on request; they are never hard-coded into generated pages or front matter.
- Recipe creation writes `recipe.md` into the selected folder and rejects folder paths outside the source directory or existing recipes.
- AI recipe generation never writes files. It returns Markdown and metadata to the editor, which saves only when the user submits the create form.
- The AI assistant can rewrite only the recipe being viewed (the update tool takes no path) and never deletes anything. The conversation is ephemeral.
- The AI integration is opt-in and uses only the configured local endpoint. `NewRecipePrompt.md` is read at startup, not when the app is built.
- Generated pages use root-absolute URLs such as `/assets/...`. They must be served from the site root; opening the HTML files directly will not load their assets.
- The server uses the port set in Configuration (default `8000`), binds to `127.0.0.1`, and has no authentication. Enable the built-in HTTPS mode (the dictation button only appears on those pages) or serve the site over HTTPS through a local reverse proxy or tunnel.
- There is no JavaScript build step. Frontend assets are served directly, and KaTeX is vendored in `src/recipeserver/assets/katex`.

## KaTeX

Updated last on 11/08/2026 to KaTeX 0.19.1 using `pnpm install katex` (see `src/recipeserver/assets/katex/README.md`).

## Documentation

Every module, script, and pinned tool carries a sibling Markdown page next to its source, named after the source file it documents — `server.py` → `server.py.md`, `scripts/docs.sh` → `scripts/docs.sh.md` — so files that share a base name stay individually documentable. Hub pages (`README.md`) keep their plain names, and every page opens with a Mermaid diagram: a map of what the page covers, right under its `#` heading, with clickable nodes (`click Node href "page.md"`) and clickable transitions (inline anchors in edge labels) that navigate the rendered site. [AGENTS.md](AGENTS.md) documents the sources and the rules for keeping them current; run `scripts/docs.sh` to render the set into `./site/` with the bundled [barnacle](https://github.com/fordaj/barnacle) binary.
