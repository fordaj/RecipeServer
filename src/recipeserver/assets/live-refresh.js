(() => {
  const POLL_INTERVAL_MS = 1500;
  const EDITOR_ID = "recipe-markdown-editor";
  const NOTICE_ID = "live-refresh-notice";

  let revision = null;
  let pendingRevision = false;
  let reloading = false;

  function editorHasUnsavedChanges() {
    const dialog = document.getElementById(EDITOR_ID);
    return Boolean(dialog && dialog.open && dialog.dataset.dirty === "true");
  }

  function reloadPage() {
    if (reloading) return;
    reloading = true;
    window.location.reload();
  }

  function showNotice() {
    let notice = document.getElementById(NOTICE_ID);
    const container = document.querySelector("dialog[open]") || document.body;

    if (notice) {
      if (notice.parentElement !== container) container.append(notice);
      return;
    }

    notice = document.createElement("div");
    notice.id = NOTICE_ID;
    notice.className = "live-refresh-notice";
    notice.setAttribute("role", "status");

    const message = document.createElement("p");
    message.className = "live-refresh-notice__message";
    message.textContent =
      "This recipe changed on disk. Your unsaved edits have been kept.";

    const reloadButton = document.createElement("button");
    reloadButton.type = "button";
    reloadButton.className = "live-refresh-notice__reload";
    reloadButton.textContent = "Reload page";
    reloadButton.addEventListener("click", reloadPage);

    const dismissButton = document.createElement("button");
    dismissButton.type = "button";
    dismissButton.className = "live-refresh-notice__dismiss";
    dismissButton.textContent = "Keep editing";
    dismissButton.addEventListener("click", () => notice.remove());

    notice.append(message, reloadButton, dismissButton);
    container.append(notice);
  }

  async function readRevision() {
    const response = await fetch("/api/revision", {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });

    if (!response.ok) {
      throw new Error(`Revision request failed (HTTP ${response.status})`);
    }

    const payload = await response.json();
    if (!Number.isFinite(payload.revision)) {
      throw new Error("Invalid revision response");
    }

    return payload.revision;
  }

  async function poll() {
    if (reloading) return;

    try {
      const current = await readRevision();

      if (revision === null) {
        revision = current;
        return;
      }

      if (current === revision) {
        if (pendingRevision && !editorHasUnsavedChanges()) reloadPage();
        return;
      }

      revision = current;
      pendingRevision = true;

      if (editorHasUnsavedChanges()) {
        showNotice();
      } else {
        reloadPage();
      }
    } catch (error) {
      // The server may be restarting; the next poll will retry.
    }
  }

  function start() {
    poll();
    window.setInterval(poll, POLL_INTERVAL_MS);

    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) poll();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
