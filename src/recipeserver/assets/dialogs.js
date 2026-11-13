/**
 * Shared dialog helpers for the recipe editor, shopping list, and the
 * index page's bulk delete. One implementation for the chrome every dialog
 * shares, so it does not drift between pages.
 */

(function () {
  // Close a <dialog> when a full press lands on its backdrop rather than its
  // contents. A drag that starts inside the dialog and ends outside it does
  // not close it, because the pointerdown must land on the dialog itself.
  function installClickOutsideClose(dialog, close) {
    let pointerDownTarget = null;

    dialog.addEventListener("pointerdown", (event) => {
      pointerDownTarget = event.target;
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog && pointerDownTarget === dialog) {
        close();
      }
      pointerDownTarget = null;
    });
  }

  // POST a bulk-delete request. Throws with the server's message on any
  // failure, including a transport or parse error.
  async function postBulkDelete(paths) {
    const response = await fetch(new URL("/api/bulk-delete", window.location.origin), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.success !== true) {
      throw new Error(result.error || `Request failed (HTTP ${response.status})`);
    }
    return result;
  }

  window.RecipeDialogs = { installClickOutsideClose, postBulkDelete };
})();
