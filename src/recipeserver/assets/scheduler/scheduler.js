(() => {
  const DIALOG_ID = "scheduler-dialog";
  const SCHEDULER_ASSETS = "/assets/scheduler";
  const SCHEDULER_API = "/api/scheduler";
  const SHOPPING_LIST_EVENT = "shopping-list";
  const SHOPPING_CART_ICON_URL = "/assets/shopping-cart.svg";

  const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
  ];

  // The number of periods rendered at a time. The window grows as the
  // view reaches either end, so the calendar never runs out of days.
  const DAY_UNITS = 121;
  const WEEK_UNITS = 41;
  const MONTH_UNITS = 25;

  let dialog = null;
  let state = null;
  let glideFrame = 0;
  let snapTimer = 0;

  // ----- Dates ----- //

  // The date of a day, as the calendar writes it.
  function isoDate(date) {
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${date.getFullYear()}-${month}-${day}`;
  }

  // The first day of the month, as the calendar writes it.
  function isoMonth(date) {
    return isoDate(new Date(date.getFullYear(), date.getMonth(), 1));
  }

  function parseDate(text) {
    const [year, month, day] = text.split("-").map(Number);
    return new Date(year, month - 1, day);
  }

  function addDays(date, amount) {
    const copy = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    copy.setDate(copy.getDate() + amount);
    return copy;
  }

  function addMonths(date, amount) {
    return new Date(date.getFullYear(), date.getMonth() + amount, 1);
  }

  function formatDate(text) {
    return parseDate(text).toLocaleDateString(undefined, {
      weekday: "long",
      month: "long",
      day: "numeric",
      year: "numeric",
    });
  }

  // The seven days of a week view page, starting with the page's date.
  function weekLabel(date) {
    const start = date;
    const end = addDays(start, 6);
    return `${MONTHS[start.getMonth()]} ${start.getDate()} – ${MONTHS[end.getMonth()]} ${end.getDate()}, ${end.getFullYear()}`;
  }

  function shortDayName(date) {
    return `${WEEKDAYS[date.getDay()]} ${date.getDate()} ${MONTHS[date.getMonth()].slice(0, 3)}`;
  }

  // ----- State ----- //

  function createState(element) {
    return {
      element,
      status: element.querySelector(".scheduler__status"),
      scroll: element.querySelector(".scheduler__scroll"),
      period: element.querySelector(".scheduler__period"),
      dateInput: element.querySelector(".scheduler__date"),
      scheduleButton: element.querySelector(".scheduler__schedule"),
      shoppingButton: element.querySelector(".scheduler__shopping"),
      selectionText: element.querySelector(".scheduler__selection"),
      selectButton: element.querySelector(".scheduler__select"),
      selectLabel: element.querySelector("[data-scheduler-select-label]"),
      recipes: [],
      byPath: new Map(),
      view: "day",
      date: new Date(),
      mode: "recipe",
      selected: new Set(),
      selectedDays: new Set(),
      dayRecipes: new Set(),
      start: new Date(),
      pageHeight: 0,
      shifting: false,
      shiftTimer: 0,
      resizeObserver: null,
    };
  }

  function setStatus(message) {
    if (state?.status) state.status.textContent = message;
  }

  // ----- API ----- //

  async function loadSchedule() {
    const response = await fetch(SCHEDULER_API, { cache: "no-store" });
    const payload = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(payload.error || `Request failed (HTTP ${response.status})`);
    }

    state.recipes = payload.recipes ?? [];
    state.byPath = new Map(state.recipes.map((recipe) => [recipe.path, recipe]));
  }

  // Saves the scheduled dates of one recipe and returns the saved dates.
  async function saveDates(path, dates) {
    const response = await fetch(SCHEDULER_API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, dates }),
    });
    const payload = await response.json().catch(() => ({}));

    if (!response.ok) {
      setStatus(payload.error || `Request failed (HTTP ${response.status})`);
      return null;
    }

    return payload.dates ?? dates;
  }

  // ----- Schedule helpers ----- //

  function recipesOn(dateText) {
    return state.recipes.filter((recipe) => recipe.dates.includes(dateText));
  }

  // The recipes that are selected on the index page.
  function indexSelection() {
    return [...document.querySelectorAll("#recipe-list .recipe-select__checkbox:checked")].map(
      (box) => box.dataset.path,
    );
  }

  // The recipes the current selection covers.
  function selectedPaths() {
    return state.mode === "day" ? [...state.dayRecipes] : [...state.selected];
  }

  // A readable text colour for a background colour.
  function contrastColor(hex) {
    const value = String(hex || "")
      .replace("#", "")
      .trim();
    if (value.length !== 6) return "#ffffff";

    const red = parseInt(value.slice(0, 2), 16);
    const green = parseInt(value.slice(2, 4), 16);
    const blue = parseInt(value.slice(4, 6), 16);
    const luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255;

    return luminance > 0.62 ? "#241f1c" : "#ffffff";
  }

  // ----- Selection ----- //

  function toggleRecipe(path) {
    if (state.selected.has(path)) {
      state.selected.delete(path);
    } else {
      state.selected.add(path);
    }
    refreshSelection();
  }

  function toggleDay(dateText) {
    if (state.selectedDays.has(dateText)) {
      state.selectedDays.delete(dateText);
    } else {
      state.selectedDays.add(dateText);
    }
    refreshSelection();
  }

  // The day selection overrides the selection made on the index page.
  function setMode(mode) {
    if (state.mode === mode) return;

    state.mode = mode;
    if (mode === "day") {
      state.selected.clear();
    } else {
      state.selectedDays.clear();
    }

    state.selectButton.setAttribute("aria-pressed", String(mode === "day"));
    state.selectLabel.textContent = mode === "day" ? "Cancel" : "Select";
    refreshSelection();
  }

  function refreshSelection() {
    state.dayRecipes = new Set();
    for (const day of state.selectedDays) {
      for (const recipe of recipesOn(day)) state.dayRecipes.add(recipe.path);
    }

    const selected = new Set(selectedPaths());

    for (const entry of state.element.querySelectorAll(".scheduler__entry")) {
      entry.classList.toggle("is-selected", selected.has(entry.dataset.path));
    }
    for (const page of state.element.querySelectorAll(".scheduler__page[data-date]")) {
      page.classList.toggle("is-selected", state.selectedDays.has(page.dataset.date));
    }
    for (const row of state.element.querySelectorAll(".scheduler__weekday")) {
      row.classList.toggle("is-selected", state.selectedDays.has(row.dataset.date));
    }
    for (const cell of state.element.querySelectorAll(".scheduler__month-day")) {
      cell.classList.toggle("is-selected", state.selectedDays.has(cell.dataset.date));
    }

    updateSelectionText();
  }

  function updateSelectionText() {
    const count = selectedPaths().length;
    const days = state.selectedDays.size;

    if (state.mode === "day") {
      state.selectionText.textContent = days
        ? `${days} day${days === 1 ? "" : "s"} selected · ${count} recipe${count === 1 ? "" : "s"}`
        : "No days selected. Use Select to pick the days to clear.";
    } else if (count) {
      state.selectionText.textContent = `${count} recipe${count === 1 ? "" : "s"} selected`;
    } else {
      state.selectionText.textContent =
        "0 recipes selected. Select recipes on the index page, then open the scheduler.";
    }

    state.shoppingButton.disabled = count === 0;
    state.scheduleButton.textContent = state.mode === "day" ? "Unschedule" : "Schedule";
    state.scheduleButton.disabled = state.mode === "day" ? days === 0 : count === 0;
  }

  // ----- Rendering ----- //

  function buildEntry(recipe, dateText, compact = false) {
    const entry = document.createElement("div");
    entry.className = compact ? "scheduler__entry scheduler__entry--compact" : "scheduler__entry";
    entry.dataset.path = recipe.path;
    entry.style.setProperty("--entry-bg", recipe.color || "#8d5542");
    entry.style.setProperty("--entry-fg", contrastColor(recipe.color));

    if (!compact && recipe.image) {
      const image = document.createElement("img");
      image.className = "scheduler__entry-image";
      image.src = recipe.image;
      image.alt = "";
      image.loading = "lazy";
      entry.append(image);
    }

    const link = document.createElement("a");
    link.className = "scheduler__entry-title";
    link.href = recipe.url;
    link.textContent = recipe.title;
    entry.append(link);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "scheduler__remove";
    remove.setAttribute("aria-label", `Remove ${recipe.title} from ${formatDate(dateText)}`);
    remove.textContent = "×";
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      unschedule(recipe, dateText);
    });
    entry.append(remove);

    entry.addEventListener("click", (event) => {
      if (event.target.closest("a, button")) return;
      if (state.mode === "day") toggleDay(dateText);
      else toggleRecipe(recipe.path);
    });

    return entry;
  }

  // The day view is a stack of single days, one per screen.
  function buildDayPage(date) {
    const dateText = isoDate(date);

    const page = document.createElement("section");
    page.className = "scheduler__page scheduler__page--day";
    page.dataset.date = dateText;
    if (dateText === isoDate(new Date())) page.classList.add("is-today");

    const header = document.createElement("button");
    header.type = "button";
    header.className = "scheduler__day-header";
    header.dataset.date = dateText;

    const weekday = document.createElement("span");
    weekday.className = "scheduler__day-weekday";
    weekday.textContent = WEEKDAYS[date.getDay()];

    const number = document.createElement("span");
    number.className = "scheduler__day-date";
    number.textContent = String(date.getDate());

    const month = document.createElement("span");
    month.className = "scheduler__day-month";
    month.textContent = `${MONTHS[date.getMonth()]} ${date.getFullYear()}`;

    header.append(weekday, number, month);
    header.addEventListener("click", () => toggleDay(dateText));

    const body = document.createElement("div");
    body.className = "scheduler__page-body";

    const recipes = recipesOn(dateText);
    for (const recipe of recipes) body.append(buildEntry(recipe, dateText));

    if (!recipes.length) {
      const empty = document.createElement("p");
      empty.className = "scheduler__empty";
      empty.textContent = "No recipes planned.";
      body.append(empty);
    }

    page.append(header, body);
    return page;
  }

  // The week view is a stack of seven-day pages, one per screen. The
  // toolbar already names the week, so the page holds only the days.
  function buildWeekPage(date) {
    const page = document.createElement("section");
    page.className = "scheduler__page scheduler__page--week";

    const days = document.createElement("div");
    days.className = "scheduler__week";

    for (let index = 0; index < 7; index += 1) {
      const day = addDays(date, index);
      const dateText = isoDate(day);

      const row = document.createElement("div");
      row.className = "scheduler__weekday";
      row.dataset.date = dateText;
      if (dateText === isoDate(new Date())) row.classList.add("is-today");

      const name = document.createElement("button");
      name.type = "button";
      name.className = "scheduler__weekday-name";
      name.textContent = shortDayName(day);
      name.addEventListener("click", () => toggleDay(dateText));

      row.append(name);
      for (const recipe of recipesOn(dateText)) row.append(buildEntry(recipe, dateText, true));

      days.append(row);
    }

    page.append(days);
    return page;
  }

  // The month view is a stack of months, one per screen. The toolbar
  // already names the month, so the page holds only the grid.
  function buildMonthPage(date) {
    const page = document.createElement("section");
    page.className = "scheduler__page scheduler__page--month";
    page.dataset.month = isoMonth(date);

    const weekdays = document.createElement("div");
    weekdays.className = "scheduler__weekdays";
    for (const name of WEEKDAYS) {
      const label = document.createElement("span");
      label.textContent = name;
      weekdays.append(label);
    }

    const grid = document.createElement("div");
    grid.className = "scheduler__month-grid";

    // The grid always has six weeks, so every month fills the screen.
    const firstOfMonth = new Date(date.getFullYear(), date.getMonth(), 1);
    const start = addDays(firstOfMonth, -firstOfMonth.getDay());

    for (let index = 0; index < 42; index += 1) {
      const day = addDays(start, index);
      const dateText = isoDate(day);

      const cell = document.createElement("div");
      cell.className = "scheduler__month-day";
      cell.dataset.date = dateText;
      if (day.getMonth() !== date.getMonth()) cell.classList.add("is-outside");
      if (dateText === isoDate(new Date())) cell.classList.add("is-today");

      const number = document.createElement("button");
      number.type = "button";
      number.className = "scheduler__month-number";
      number.textContent = String(day.getDate());
      number.addEventListener("click", () => toggleDay(dateText));

      cell.append(number);
      for (const recipe of recipesOn(dateText)) cell.append(buildEntry(recipe, dateText, true));

      grid.append(cell);
    }

    page.append(weekdays, grid);
    return page;
  }

  function renderPeriod() {
    if (state.view === "day") {
      state.period.textContent = formatDate(isoDate(state.date));
    } else if (state.view === "week") {
      state.period.textContent = weekLabel(state.date);
    } else {
      state.period.textContent = `${MONTHS[state.date.getMonth()]} ${state.date.getFullYear()}`;
    }
  }

  // ----- The scrolling window ----- //

  const unitDays = () => (state.view === "week" ? 7 : 1);

  const unitCount = () => {
    if (state.view === "week") return WEEK_UNITS;
    if (state.view === "month") return MONTH_UNITS;
    return DAY_UNITS;
  };

  // The date a page starts on. A month page always starts on the first.
  function unitAnchor(date) {
    if (state.view === "month") return addMonths(date, 0);
    return new Date(date.getFullYear(), date.getMonth(), date.getDate());
  }

  function addUnits(date, amount) {
    if (state.view === "month") return addMonths(date, amount);
    return addDays(date, amount * unitDays());
  }

  function buildPage(date) {
    if (state.view === "week") return buildWeekPage(date);
    if (state.view === "month") return buildMonthPage(date);
    return buildDayPage(date);
  }

  function renderPages() {
    // A glide that is still settling must not fight the rebuilt calendar.
    window.cancelAnimationFrame(glideFrame);
    window.clearTimeout(snapTimer);
    glideFrame = 0;

    const half = Math.floor(unitCount() / 2);
    state.start = addUnits(unitAnchor(state.date), -half);

    const fragment = document.createDocumentFragment();
    for (let index = 0; index < unitCount(); index += 1) {
      fragment.append(buildPage(addUnits(state.start, index)));
    }

    state.scroll.replaceChildren(fragment);

    // The pages are exactly one screen tall. The height is read from the
    // rendered page so a fractional layout height is kept.
    state.pageHeight =
      state.scroll.firstElementChild?.getBoundingClientRect().height ||
      state.scroll.getBoundingClientRect().height;

    // The focused page is the one in the middle of the window.
    state.scroll.scrollTop = half * state.pageHeight;
    refreshSelection();
  }

  // A change in the size of the calendar (a resize, a wrapped footer, or
  // the first real layout) changes the height of a page, so the calendar
  // is rebuilt around the day it is showing.
  function observeSize() {
    if (!("ResizeObserver" in window) || state.resizeObserver) return;

    state.resizeObserver = new ResizeObserver(() => {
      const height = state.scroll.getBoundingClientRect().height;
      if (!height || Math.abs(height - state.pageHeight) < 1) return;
      renderPages();
    });

    state.resizeObserver.observe(state.scroll);
  }

  // Grows the window at one end so the view never runs out of pages. The
  // pages are added and removed at the far ends, so the page that is in
  // view stays where it is.
  function shiftWindow(direction) {
    if (state.shifting || !state.pageHeight) return;

    state.shifting = true;
    window.clearTimeout(state.shiftTimer);
    state.shiftTimer = window.setTimeout(() => {
      state.shifting = false;
    }, 80);

    const units = Math.floor(unitCount() / 2);
    const fragment = document.createDocumentFragment();

    if (direction < 0) {
      const start = addUnits(state.start, -units);
      for (let index = 0; index < units; index += 1) {
        fragment.append(buildPage(addUnits(start, index)));
      }

      state.scroll.prepend(fragment);
      state.start = start;
      // The pages that were in view moved down.
      state.scroll.scrollTop += units * state.pageHeight;
      trimPages("bottom");
      return;
    }

    for (let index = 0; index < units; index += 1) {
      fragment.append(buildPage(addUnits(state.start, unitCount() + index)));
    }

    state.scroll.append(fragment);
    trimPages("top");
  }

  // Removes the pages that fell out of the window at the far end.
  function trimPages(side) {
    const units = Math.floor(unitCount() / 2);

    for (let index = 0; index < units; index += 1) {
      const element =
        side === "bottom" ? state.scroll.lastElementChild : state.scroll.firstElementChild;
      if (!element) break;

      element.remove();

      if (side === "top") {
        state.start = addUnits(state.start, 1);
        // The pages that were in view moved up.
        state.scroll.scrollTop -= state.pageHeight;
      }
    }
  }

  // ----- Scrolling and snapping ----- //

  function onScroll() {
    if (!state.pageHeight) return;

    const top = state.scroll.scrollTop / state.pageHeight;
    const bottom = (state.scroll.scrollTop + state.scroll.clientHeight) / state.pageHeight;

    if (!state.shifting) {
      if (top <= 0) {
        shiftWindow(-1);
      } else if (bottom >= unitCount()) {
        shiftWindow(1);
      }
    }

    updateFocusedDate();
    scheduleSnap();
  }

  // The page in the middle of the window is the one the view is about.
  function updateFocusedDate() {
    if (!state.pageHeight) return;

    const index = Math.max(
      0,
      Math.min(unitCount() - 1, Math.round(state.scroll.scrollTop / state.pageHeight)),
    );
    const anchor = addUnits(state.start, index);

    const current = state.view === "month" ? isoMonth(state.date) : isoDate(state.date);
    const next = state.view === "month" ? isoMonth(anchor) : isoDate(anchor);
    if (next === current) return;

    state.date = anchor;
    renderPeriod();
    if (document.activeElement !== state.dateInput) state.dateInput.value = isoDate(anchor);
  }

  function scheduleSnap() {
    window.clearTimeout(snapTimer);
    snapTimer = window.setTimeout(snapPage, 300);
  }

  // The snap strength is a CSS setting, so the calendar can be tuned for
  // every screen without a control on the page.
  function snapStrength() {
    const raw = getComputedStyle(state.element)
      .getPropertyValue("--scheduler-snap-strength")
      .trim();
    const value = Number.parseFloat(raw);

    return Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0.6;
  }

  // Pulls the calendar to the nearest page. The snap strength decides how
  // hard the calendar is pulled, so a low setting glides and a high one snaps.
  function snapPage() {
    const strength = snapStrength();
    if (strength <= 0 || !state.pageHeight) return;

    const offset = state.scroll.scrollTop;
    const target = Math.round(offset / state.pageHeight) * state.pageHeight;
    if (Math.abs(target - offset) < 1) return;

    glideTo(target, strength);
  }

  function glideTo(target, strength) {
    window.cancelAnimationFrame(glideFrame);

    const step = () => {
      const difference = target - state.scroll.scrollTop;
      // The last step is set outright: the browser keeps the scroll
      // position on whole pixels, so a smaller step would never arrive.
      if (Math.abs(difference) <= 2) {
        state.scroll.scrollTop = target;
        glideFrame = 0;
        return;
      }

      const next = Math.round(state.scroll.scrollTop + difference * (0.06 + 0.26 * strength));

      // A fractional target can round to the pixel the view is already
      // on. Set the target outright in that case instead of spinning.
      if (next === state.scroll.scrollTop) {
        state.scroll.scrollTop = target;
        glideFrame = 0;
        return;
      }

      state.scroll.scrollTop = next;
      glideFrame = window.requestAnimationFrame(step);
    };

    glideFrame = window.requestAnimationFrame(step);
  }

  // ----- Navigation ----- //

  function setView(view) {
    state.view = view;

    for (const button of state.element.querySelectorAll("[data-scheduler-view]")) {
      button.setAttribute("aria-pressed", String(button.dataset.schedulerView === view));
    }

    renderPeriod();
    renderPages();
  }

  function step(amount) {
    if (state.view === "month") {
      state.date = addMonths(state.date, amount);
    } else {
      state.date = addDays(state.date, amount * unitDays());
    }

    state.dateInput.value = isoDate(state.date);
    renderPeriod();
    renderPages();
  }

  // ----- Actions ----- //

  async function scheduleSelected() {
    const date = state.dateInput.value;
    if (!date) {
      setStatus("Choose a date first.");
      return;
    }

    const paths = [...state.selected];
    if (!paths.length) {
      setStatus("No recipes selected.");
      return;
    }

    setStatus("Saving…");

    for (const path of paths) {
      const recipe = state.byPath.get(path);
      if (!recipe) continue;

      const dates = recipe.dates.includes(date) ? recipe.dates : [...recipe.dates, date].sort();
      const saved = await saveDates(path, dates);
      if (!saved) return;

      recipe.dates = saved;
    }

    setStatus(
      `Scheduled ${paths.length} recipe${paths.length === 1 ? "" : "s"} for ${formatDate(date)}.`,
    );
    renderPages();
    refreshSelection();
  }

  async function unscheduleSelectedDays() {
    const days = [...state.selectedDays];
    if (!days.length) {
      setStatus("No days selected.");
      return;
    }

    setStatus("Saving…");

    const updates = new Map();
    for (const day of days) {
      for (const recipe of recipesOn(day)) {
        const dates = updates.get(recipe.path) ?? recipe.dates;
        updates.set(
          recipe.path,
          dates.filter((date) => date !== day),
        );
      }
    }

    for (const [path, dates] of updates) {
      const saved = await saveDates(path, dates);
      if (!saved) return;

      const recipe = state.byPath.get(path);
      if (recipe) recipe.dates = saved;
    }

    setStatus(
      `Removed ${updates.size} recipe${updates.size === 1 ? "" : "s"} from ${days.length} day${days.length === 1 ? "" : "s"}.`,
    );

    state.selectedDays.clear();
    renderPages();
    refreshSelection();
  }

  async function unschedule(recipe, dateText) {
    const dates = recipe.dates.filter((date) => date !== dateText);
    const saved = await saveDates(recipe.path, dates);
    if (!saved) return;

    recipe.dates = saved;
    setStatus(`Removed ${recipe.title} from ${formatDate(dateText)}.`);
    renderPages();
    refreshSelection();
  }

  // Opens the shopping list with the recipes the scheduler has selected,
  // then closes the calendar so the list takes over the screen.
  function openShoppingList() {
    const paths = selectedPaths();
    if (!paths.length) return;

    dialog.close();
    document.dispatchEvent(new CustomEvent(SHOPPING_LIST_EVENT, { detail: { paths } }));
  }

  // ----- Icons ----- //

  // The icon is fetched and inlined so it inherits the button colour
  // through currentColor.
  async function loadSvgIcon(url) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) return "";

      const svg = new DOMParser().parseFromString(
        await response.text(),
        "image/svg+xml",
      ).documentElement;
      svg.setAttribute("aria-hidden", "true");
      svg.setAttribute("focusable", "false");
      return new XMLSerializer().serializeToString(svg);
    } catch {
      return "";
    }
  }

  async function loadIcons(element) {
    const icon = await loadSvgIcon(SHOPPING_CART_ICON_URL);
    const target = element.querySelector(".scheduler__shopping .scheduler__icon");
    if (target && icon) target.innerHTML = icon;
  }

  // ----- Dialog wiring ----- //

  async function createDialog() {
    const response = await fetch(`${SCHEDULER_ASSETS}/scheduler.html`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Failed to load the scheduler (HTTP ${response.status})`);
    }

    const element = document.createElement("dialog");
    element.id = DIALOG_ID;
    element.className = "scheduler-dialog";
    element.innerHTML = await response.text();
    document.body.append(element);
    return element;
  }

  function registerListeners(element) {
    element.querySelector(".scheduler__close")?.addEventListener("click", () => element.close());

    element.querySelectorAll("[data-scheduler-view]").forEach((button) => {
      button.addEventListener("click", () => setView(button.dataset.schedulerView));
    });

    element.querySelectorAll("[data-scheduler-step]").forEach((button) => {
      button.addEventListener("click", () => step(Number(button.dataset.schedulerStep)));
    });

    element.querySelector(".scheduler__today")?.addEventListener("click", () => {
      state.date = new Date();
      state.dateInput.value = isoDate(state.date);
      renderPeriod();
      renderPages();
    });

    element.querySelector(".scheduler__select")?.addEventListener("click", () => {
      setMode(state.mode === "day" ? "recipe" : "day");
    });

    element.querySelector(".scheduler__schedule")?.addEventListener("click", () => {
      if (state.mode === "day") unscheduleSelectedDays();
      else scheduleSelected();
    });

    element.querySelector(".scheduler__shopping")?.addEventListener("click", openShoppingList);

    // Picking a date moves the calendar to that day.
    element.querySelector(".scheduler__date")?.addEventListener("change", (event) => {
      if (!event.target.value) return;
      state.date = parseDate(event.target.value);
      renderPeriod();
      renderPages();
    });

    state.scroll?.addEventListener("scroll", onScroll, { passive: true });

    // Clicking the backdrop closes the scheduler.
    let pointerDownTarget = null;
    element.addEventListener("pointerdown", (event) => {
      pointerDownTarget = event.target;
    });
    element.addEventListener("click", (event) => {
      if (event.target === element && pointerDownTarget === element) element.close();
      pointerDownTarget = null;
    });
  }

  // ----- Opening ----- //

  async function openScheduler() {
    try {
      if (!dialog) {
        dialog = await createDialog();
        state = createState(dialog);
        registerListeners(dialog);
        observeSize();
        loadIcons(dialog);
      }

      if (!dialog.open) dialog.showModal();

      setStatus("Loading…");

      await loadSchedule();

      // The recipes that were selected on the index page come with the
      // scheduler, so they can be scheduled right away.
      state.mode = "recipe";
      state.selectedDays.clear();
      state.selectButton.setAttribute("aria-pressed", "false");
      state.selectLabel.textContent = "Select";
      state.selected = new Set(indexSelection());

      state.date = new Date();
      state.dateInput.value = isoDate(state.date);
      renderPeriod();
      renderPages();
      refreshSelection();
      setStatus("");
    } catch (error) {
      setStatus(error.message || "Unable to load the schedule.");
    }
  }

  function initialize() {
    document.querySelector("#scheduler")?.addEventListener("click", openScheduler);
    document.addEventListener("scheduler", openScheduler);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }
})();
