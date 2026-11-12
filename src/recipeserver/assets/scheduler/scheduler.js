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
      weekdays: element.querySelector(".scheduler__weekdays"),
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
      shifting: false,
      viewportHeight: 0,
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

    // The shopping list is a day-selection action, so it only shows while
    // the scheduler is in selection mode.
    state.shoppingButton.hidden = state.mode !== "day";
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

    // In selection mode a click anywhere in the day picks the day, even
    // on a recipe. Otherwise a recipe opens its page, and the entry body
    // toggles the recipe.
    entry.addEventListener("click", (event) => {
      if (state.mode === "day") {
        event.preventDefault();
        toggleDay(dateText);
        return;
      }
      if (event.target.closest("a, button")) return;
      toggleRecipe(recipe.path);
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

  // The week view is a stack of seven-day pages. Each day grows to show
  // all of its recipes. The toolbar already names the week, so the page
  // holds only the days.
  function buildWeekPage(date) {
    const page = document.createElement("section");
    page.className = "scheduler__page scheduler__page--week";
    page.dataset.date = isoDate(date);

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
  // already names the month and the weekday row is frozen above the
  // calendar, so the page holds only the grid.
  function buildMonthPage(date) {
    const page = document.createElement("section");
    page.className = "scheduler__page scheduler__page--month";
    page.dataset.month = isoMonth(date);

    const grid = document.createElement("div");
    grid.className = "scheduler__month-grid";

    // The grid always has six weeks, so every month fills the screen.
    const firstOfMonth = new Date(date.getFullYear(), date.getMonth(), 1);
    const start = addDays(firstOfMonth, -firstOfMonth.getDay());

    for (let week = 0; week < 6; week += 1) {
      const row = document.createElement("div");
      row.className = "scheduler__month-week";

      for (let weekday = 0; weekday < 7; weekday += 1) {
        const day = addDays(start, week * 7 + weekday);
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

        row.append(cell);
      }

      grid.append(row);
    }

    page.append(grid);
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
    const half = Math.floor(unitCount() / 2);
    state.start = addUnits(unitAnchor(state.date), -half);

    const fragment = document.createDocumentFragment();
    for (let index = 0; index < unitCount(); index += 1) {
      fragment.append(buildPage(addUnits(state.start, index)));
    }

    // The weekday row is a frozen pane above the months, so it stays at
    // the top of the scroll container while the pages replace each other.
    state.scroll.replaceChildren(state.weekdays, fragment);

    // The focused page sits at the top of the view. A page is at least a
    // screen tall, so the calendar opens on the whole day, week or month.
    const headerHeight = state.weekdays.hidden ? 0 : state.weekdays.offsetHeight;
    const focused = pages()[half];
    if (focused) state.scroll.scrollTop = focused.offsetTop - headerHeight;
    refreshSelection();
  }

  function pages() {
    return state.scroll.querySelectorAll(":scope > .scheduler__page");
  }

  // The footer can wrap after its icons load, which changes how tall the
  // calendar is. Rebuild around the focused page when that happens so the
  // page in view stays lined up with the top of the calendar.
  function observeSize() {
    if (!("ResizeObserver" in window) || state.resizeObserver) return;

    state.resizeObserver = new ResizeObserver(() => {
      const height = state.scroll.clientHeight;
      if (!height || height === state.viewportHeight) return;

      state.viewportHeight = height;
      renderPages();
    });

    state.resizeObserver.observe(state.scroll);
  }

  // The page at the top of the view is the one the calendar is showing.
  function currentPage() {
    const headerHeight = state.weekdays.hidden ? 0 : state.weekdays.offsetHeight;
    const top = state.scroll.scrollTop + headerHeight + 1;
    const list = pages();

    for (const page of list) {
      if (page.offsetTop + page.offsetHeight > top) return page;
    }

    return list[list.length - 1] ?? null;
  }

  // Grows the window at one end so the view never runs out of pages. The
  // window is trimmed at the other end, and the scroll position is moved
  // by the height that was added or removed so the view stays still.
  function shiftWindow(direction) {
    if (state.shifting) return;

    state.shifting = true;
    requestAnimationFrame(() => {
      state.shifting = false;
    });

    const units = Math.floor(unitCount() / 2);

    if (direction < 0) {
      const start = addUnits(state.start, -units);
      const fragment = document.createDocumentFragment();
      for (let index = 0; index < units; index += 1) {
        fragment.append(buildPage(addUnits(start, index)));
      }

      const height = state.scroll.scrollHeight;
      // The weekday row stays first so it remains the frozen pane.
      state.weekdays.after(fragment);
      state.start = start;
      // The pages that were in view moved down by the added height.
      state.scroll.scrollTop += state.scroll.scrollHeight - height;

      for (let index = 0; index < units; index += 1) {
        state.scroll.lastElementChild?.remove();
      }
      return;
    }

    const fragment = document.createDocumentFragment();
    for (let index = 0; index < units; index += 1) {
      fragment.append(buildPage(addUnits(state.start, unitCount() + index)));
    }
    state.scroll.append(fragment);

    // The pages that were in view moved up by the height of the pages
    // that are trimmed from the top.
    for (let index = 0; index < units; index += 1) {
      const page = state.weekdays.nextElementSibling;
      if (!page) break;

      const height = page.offsetHeight;
      page.remove();
      state.start = addUnits(state.start, 1);
      state.scroll.scrollTop = Math.max(0, state.scroll.scrollTop - height);
    }
  }

  // ----- Scrolling ----- //

  function onScroll() {
    if (state.scroll.scrollTop <= 0) {
      shiftWindow(-1);
    } else if (
      state.scroll.scrollTop + state.scroll.clientHeight >=
      state.scroll.scrollHeight - 1
    ) {
      shiftWindow(1);
    }

    updateFocusedDate();
  }

  // The page at the top of the view is the one the toolbar names.
  function updateFocusedDate() {
    const page = currentPage();
    if (!page) return;

    const anchor =
      state.view === "month" ? parseDate(page.dataset.month) : parseDate(page.dataset.date);

    const current = state.view === "month" ? isoMonth(state.date) : isoDate(state.date);
    const next = state.view === "month" ? isoMonth(anchor) : isoDate(anchor);
    if (next === current) return;

    state.date = anchor;
    renderPeriod();
    if (document.activeElement !== state.dateInput) state.dateInput.value = isoDate(anchor);
  }

  // ----- Navigation ----- //

  function setView(view) {
    state.view = view;

    for (const button of state.element.querySelectorAll("[data-scheduler-view]")) {
      button.setAttribute("aria-pressed", String(button.dataset.schedulerView === view));
    }

    // The weekday row is the frozen pane of the month view only.
    state.weekdays.hidden = view !== "month";

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
