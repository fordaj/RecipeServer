(() => {
  // Optional OIDC UI. Generated pages are static and shared by every visitor,
  // so permission-specific controls cannot be baked into the HTML at
  // generation time. This script reads /api/auth/status and adjusts the page
  // at runtime; the server enforces the same rules on every request.

  const STATUS_URL = "/api/auth/status";
  const SETTINGS_URL = "/api/auth/settings";
  const LOGOUT_URL = "/api/auth/logout";
  const ICONS = {
    signIn: "/assets/log-in.svg",
    signOut: "/assets/log-out.svg",
    access: "/assets/shield.svg",
  };

  let status = null;
  let state = { applied: false };

  function menuPanel() {
    return document.querySelector(".sandwich-menu__panel");
  }

  async function icon(url, className) {
    const load = window.RecipeIcons?.loadSvgIcon;
    if (!load) return "";
    const svg = await load(url, { class: className });
    return svg || "";
  }

  function menuButton(label, attributes, iconUrl, name = "") {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "sandwich-menu__item";
    button.setAttribute("role", "menuitem");
    for (const [name, value] of Object.entries(attributes)) button.setAttribute(name, value);
    const labelSpan = document.createElement("span");
    if (name) {
      // The signed-in user's name shares the Sign out row, separated by a
      // dot. Values come from /api/auth/status, never from the config API.
      const user = document.createElement("span");
      user.className = "sandwich-menu__status";
      user.textContent = name;
      const separator = document.createElement("span");
      separator.className = "sandwich-menu__status-dot";
      separator.setAttribute("aria-hidden", "true");
      separator.textContent = "·";
      labelSpan.append(document.createTextNode(label), separator, user);
    } else {
      labelSpan.textContent = label;
    }
    button.append(labelSpan);
    if (iconUrl) {
      icon(iconUrl, "sandwich-menu__item-icon").then((svg) => {
        if (svg) button.insertAdjacentHTML("afterbegin", svg);
      });
    }
    return button;
  }

  function hideEditingControls(canEdit) {
    if (canEdit) return;
    for (const selector of [
      "[data-config]",
      "[data-archive]",
      "#create-recipe",
      "#edit-recipe",
      "[data-timeline]",
      "[data-bulk-delete]",
      "[data-shopping-list]",
    ]) {
      for (const element of document.querySelectorAll(selector)) element.hidden = true;
    }
    // The assistant is created asynchronously, after /api/ai-status resolves.
    const hideAssistant = () => {
      for (const element of document.querySelectorAll(".ai-assistant")) element.remove();
    };
    hideAssistant();
    if (!state.observer) {
      state.observer = new MutationObserver(hideAssistant);
      state.observer.observe(document.body, { childList: true, subtree: true });
    }
  }

  function addAuthMenuItems() {
    const panel = menuPanel();
    if (!panel || !status?.enabled || state.applied) return;
    state.applied = true;
    const anchor = panel.querySelector(".sandwich-menu__status");
    const insert = (element) => panel.insertBefore(element, anchor || null);

    if (status.authenticated) {
      const logout = menuButton(
        "Sign out",
        { "data-auth-logout": "" },
        ICONS.signOut,
        status.name || "",
      );
      logout.addEventListener("click", () => signOut(logout));
      insert(logout);
    } else {
      const login = menuButton("Sign in", { "data-auth-login": "" }, ICONS.signIn);
      login.addEventListener("click", () => {
        window.location.href = `${status.loginUrl}?next=${encodeURIComponent(window.location.pathname + window.location.search)}`;
      });
      insert(login);
    }

    if (status.isOwner) {
      const access = menuButton("Access settings", { "data-access-settings": "" }, ICONS.access);
      access.addEventListener("click", () => openAccessDialog());
      insert(access);
    }
  }

  async function signOut(button) {
    button.disabled = true;
    try {
      const response = await fetch(LOGOUT_URL, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": status.csrfToken || "" },
        body: "{}",
      });
      if (!response.ok) throw new Error("Sign out failed");
      window.location.reload();
    } catch {
      button.disabled = false;
    }
  }

  function buildAccessDialog() {
    const dialog = document.createElement("dialog");
    dialog.className = "access-settings-dialog";
    const form = document.createElement("form");
    form.className = "access-settings";
    form.method = "dialog";

    const header = document.createElement("header");
    header.className = "access-settings__header";
    const title = document.createElement("h2");
    title.textContent = "Access settings";
    header.append(title);
    form.append(header);

    const levels = [
      ["none", "None — no application access"],
      ["view", "View — browse and search"],
      ["edit", "Edit — create, modify, and delete"],
    ];
    const selects = {};
    for (const [key, label] of [
      ["guest", "Guest access"],
      ["authenticated", "Authenticated access"],
    ]) {
      const wrapper = document.createElement("label");
      wrapper.className = "config-editor__field";
      const text = document.createElement("span");
      text.textContent = label;
      const select = document.createElement("select");
      for (const [value, optionLabel] of levels) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = optionLabel;
        select.append(option);
      }
      selects[key] = select;
      text.append(select);
      wrapper.append(text);
      form.append(wrapper);
    }

    const statusLine = document.createElement("p");
    statusLine.className = "config-editor__status";
    statusLine.setAttribute("role", "status");
    form.append(statusLine);

    const footer = document.createElement("footer");
    footer.className = "config-editor__footer";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", () => dialog.close());
    const save = document.createElement("button");
    save.type = "button";
    save.textContent = "Save";
    save.addEventListener("click", async () => {
      save.disabled = true;
      statusLine.textContent = "Saving…";
      try {
        const response = await fetch(SETTINGS_URL, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": status.csrfToken || "" },
          body: JSON.stringify({
            guest: selects.guest.value,
            authenticated: selects.authenticated.value,
          }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Unable to save access settings");
        dialog.close();
        window.location.reload();
      } catch (error) {
        statusLine.textContent = error.message;
        save.disabled = false;
      }
    });
    footer.append(cancel, save);
    form.append(footer);
    dialog.append(form);
    document.body.append(dialog);
    return { dialog, selects, statusLine };
  }

  async function openAccessDialog() {
    if (state.accessDialog) {
      try {
        const response = await fetch(SETTINGS_URL, { credentials: "same-origin" });
        if (response.ok) {
          const values = await response.json();
          state.accessDialog.selects.guest.value = values.guest;
          state.accessDialog.selects.authenticated.value = values.authenticated;
        }
      } catch {
        // Keep the last known values; the save will report any problem.
      }
      state.accessDialog.statusLine.textContent = "";
      state.accessDialog.dialog.showModal();
      return;
    }
    state.accessDialog = buildAccessDialog();
    await openAccessDialog();
  }

  const originalFetch = window.fetch.bind(window);

  async function loadStatus() {
    try {
      const response = await originalFetch(STATUS_URL, { credentials: "same-origin" });
      return response.ok ? await response.json() : null;
    } catch {
      return null;
    }
  }

  // Start the status request as soon as this script runs. The token is needed
  // by writes from every other page script, including ones the visitor can
  // trigger before the menu finishes initializing.
  const statusReady = loadStatus().then((value) => {
    status = value;
    return value;
  });

  const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

  function sameOriginMutation(input, init) {
    const method = (
      init?.method ||
      (input instanceof Request ? input.method : "GET") ||
      "GET"
    ).toUpperCase();
    if (!MUTATING_METHODS.has(method)) return false;
    let url;
    try {
      url = new URL(input instanceof Request ? input.url : String(input), window.location.href);
    } catch {
      return false;
    }
    return url.origin === window.location.origin;
  }

  function withCsrfToken(input, init) {
    if (!status?.csrfToken) return init;
    const headers = new Headers(
      init?.headers ?? (input instanceof Request ? input.headers : undefined),
    );
    if (headers.has("X-CSRF-Token")) return init;
    headers.set("X-CSRF-Token", status.csrfToken);
    return { ...init, headers };
  }

  // The server requires X-CSRF-Token on every mutation once the visitor is
  // signed in. Generated pages are static and shared, so no other script can
  // know the token: attach it centrally to same-origin writes instead of
  // editing every fetch call site. Also turn a 401 from any page script into
  // a sign-in redirect.
  window.fetch = async (input, init) => {
    const needsToken = sameOriginMutation(input, init);
    if (needsToken) await statusReady;
    const response = await originalFetch(input, needsToken ? withCsrfToken(input, init) : init);
    if (response.status === 401 && status?.enabled) {
      const url =
        typeof input === "string" ? input : input instanceof Request ? input.url : input?.url || "";
      if (!url.includes(STATUS_URL)) {
        try {
          const data = await response.clone().json();
          if (data.loginUrl) window.location.href = data.loginUrl;
        } catch {
          // Not a JSON 401; leave it to the caller.
        }
      }
    }
    return response;
  };

  async function init() {
    const current = await statusReady;
    if (!current?.enabled) return;
    hideEditingControls(current.canEdit);
    addAuthMenuItems();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
