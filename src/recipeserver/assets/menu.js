// Sandwich menu: toggle the panel and trigger archive downloads.
// The download date is built from local date components so the filename
// reflects the browser's timezone, not UTC (toISOString would be UTC).

const initSandwichMenu = () => {
  document.querySelectorAll(".sandwich-menu").forEach((menu) => {
    const toggle = menu.querySelector(".sandwich-menu__toggle");
    const panel = menu.querySelector(".sandwich-menu__panel");
    const status = menu.querySelector(".sandwich-menu__status");
    if (!toggle || !panel) return;

    const close = () => {
      panel.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
    };

    const open = () => {
      panel.hidden = false;
      toggle.setAttribute("aria-expanded", "true");
    };

    toggle.addEventListener("click", () => (panel.hidden ? open() : close()));

    document.addEventListener("click", (event) => {
      if (!menu.contains(event.target)) close();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        close();
        toggle.focus();
      }
    });

    const browserDate = () => {
      const now = new Date();
      const pad = (value) => String(value).padStart(2, "0");
      return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
    };

    const filenameFor = (kind, date) =>
      `${date}_RecipeServer_${kind === "source" ? "Source" : "Site"}.7z`;

    const filenameFromHeaders = (response, fallback) => {
      const disposition = response.headers.get("Content-Disposition") || "";
      const match = /filename="([^"]+)"/.exec(disposition);
      return match ? match[1] : fallback;
    };

    panel.querySelectorAll("[data-schedule]").forEach((item) => {
      item.addEventListener("click", () => {
        close();
        // The scheduler listens for this event, so the menu stays
        // independent of the pages that include it.
        document.dispatchEvent(new CustomEvent("scheduler"));
      });
    });

    panel.querySelectorAll("[data-archive]").forEach((item) => {
      item.addEventListener("click", async () => {
        if (item.disabled) return;

        const kind = item.dataset.archive;
        const localDate = browserDate();
        item.disabled = true;

        if (status) {
          status.hidden = false;
          status.textContent = `Preparing ${filenameFor(kind, localDate)}…`;
        }

        try {
          const response = await fetch(
            `/api/archive/${kind}?date=${encodeURIComponent(localDate)}`,
            { cache: "no-store" },
          );
          if (!response.ok) {
            throw new Error(`Download failed (${response.status})`);
          }

          const filename = filenameFromHeaders(response, filenameFor(kind, localDate));
          const blob = await response.blob();
          const url = URL.createObjectURL(blob);
          const link = document.createElement("a");
          link.href = url;
          link.download = filename;
          document.body.appendChild(link);
          link.click();
          link.remove();
          URL.revokeObjectURL(url);

          if (status) status.textContent = `Downloaded ${filename}.`;
          setTimeout(close, 1200);
        } catch {
          if (status) status.textContent = "Download failed. Please try again.";
        } finally {
          item.disabled = false;
        }
      });
    });
  });
};

document.addEventListener("DOMContentLoaded", initSandwichMenu);
