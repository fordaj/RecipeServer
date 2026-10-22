
(() => {
    const EDITOR_ID = "recipe-markdown-editor";

    function createEditor() {
        const dialog = document.createElement("dialog");
        dialog.id = EDITOR_ID;
        dialog.className = "recipe-editor-dialog";

        dialog.innerHTML = `
            <form class="recipe-editor" method="dialog">
                <header class="recipe-editor__header">
                    <h2>Edit Markdown</h2>
                    <button
                        type="button"
                        class="recipe-editor__close"
                        aria-label="Close editor"
                    >&times;</button>
                </header>

                <p class="recipe-editor__status" role="status"></p>

                <textarea
                    class="recipe-editor__source"
                    aria-label="Markdown source"
                    spellcheck="false"
                    required
                ></textarea>

                <footer class="recipe-editor__footer">
                    <button type="button" class="recipe-editor__cancel">
                        Cancel
                    </button>
                    <button type="submit" class="recipe-editor__save">
                        Save
                    </button>
                </footer>
            </form>
        `;

        document.body.append(dialog);
        return dialog;
    }

    function getMarkdownPath() {
        // Derive the source path from the current HTML page.
        const page = decodeURIComponent(
            window.location.pathname.replace(/^\/+/, "")
        );

        return page.replace(/\.html$/i, ".md");
    }

    async function readMarkdown(path) {
        const url = new URL("/api/markdown", window.location.origin);
        url.searchParams.set("path", path);

        const response = await fetch(url, { cache: "no-store" });

        if (!response.ok) {
            throw new Error(`Unable to load Markdown (HTTP ${response.status})`);
        }

        return response.text();
    }

    async function saveMarkdown(path, content) {
        const response = await fetch("/api/markdown", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ path, content }),
        });

        const result = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(
                result.error || `Unable to save (HTTP ${response.status})`
            );
        }
    }

    function initialize() {
        const button = document.querySelector("#edit-recipe");
        if (!button) return;

        const dialog = createEditor();
        const form = dialog.querySelector("form");
        const textarea = dialog.querySelector("textarea");
        const status = dialog.querySelector(".recipe-editor__status");
        const saveButton = dialog.querySelector(".recipe-editor__save");
        const cancelButton = dialog.querySelector(".recipe-editor__cancel");
        const closeButton = dialog.querySelector(".recipe-editor__close");

        let originalContent = "";
        let busy = false;

        let scrollY = 0;

function lockBackgroundScroll() {
    scrollY = window.scrollY;

    document.body.style.position = "fixed";
    document.body.style.top = `-${scrollY}px`;
    document.body.style.left = "0";
    document.body.style.right = "0";
    document.body.style.width = "100%";
}

function unlockBackgroundScroll() {
    document.body.style.position = "";
    document.body.style.top = "";
    document.body.style.left = "";
    document.body.style.right = "";
    document.body.style.width = "";

    window.scrollTo(0, scrollY);
}

        function setBusy(value) {
            busy = value;
            saveButton.disabled = value;
            cancelButton.disabled = value;
            closeButton.disabled = value;
            textarea.readOnly = value;
            button.disabled = value;
        }

        function closeEditor() {
            if (!busy && dialog.open) dialog.close();
        }
        
          
          
          
          async function openEditor() {
            if (busy) return;
            
            document.body.classList.add("recipe-editor-open");

            lockBackgroundScroll();
            dialog.showModal();

            status.textContent = "Loading Markdown…";
            textarea.value = "";
            setBusy(true);

            try {
                originalContent = await readMarkdown(getMarkdownPath());
                textarea.value = originalContent;
                status.textContent = "";
                // Don't autofocus: let the user tap when ready to type.
            } catch (error) {
                status.textContent = error.message;
            } finally {
                setBusy(false);
            }
        }
        
        dialog.addEventListener("close", () => {
            document.body.classList.remove("recipe-editor-open");
            unlockBackgroundScroll();
        });

        button.addEventListener("click", openEditor);
        cancelButton.addEventListener("click", closeEditor);
        closeButton.addEventListener("click", closeEditor);
        dialog.addEventListener("close", unlockBackgroundScroll);

        dialog.addEventListener("cancel", (event) => {
            if (busy) event.preventDefault();
        });

        form.addEventListener("submit", async (event) => {
            event.preventDefault();

            if (busy) return;

            const content = textarea.value;

            if (content === originalContent) {
                dialog.close();
                return;
            }

            setBusy(true);
            status.textContent = "Saving Markdown…";

            try {
                await saveMarkdown(getMarkdownPath(), content);
                status.textContent = "Saved! Reloading…";
                window.location.reload();
            } catch (error) {
                status.textContent = error.message;
                setBusy(false);
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize);
    } else {
        initialize();
    }

    
})();
