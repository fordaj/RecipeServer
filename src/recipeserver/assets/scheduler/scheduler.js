(() => {
  const DIALOG_ID = "scheduler-dialog";
  const SCHEDULER_ASSETS = "/assets/scheduler";
  const SCHEDULER_API = "/api/scheduler";
  const SNAP_KEY = "recipe-scheduler-snap";

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

  // The day and week views scroll sideways without an end. These are the
  // sizes of the window that is rendered at a time.
  const DAY_WIDTH = 250;
  const WEEK_WIDTH = 320;
  const DAY_UNITS = 121;
  const WEEK_UNITS = 31;
  const MONTH_UNITS = 25;

  // How close to the edge the view has to come before the window grows.
  const EDGE = 260;

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

  function startOfWeek(date) {
    return addDays(date, -date.getDay());
  }

  // The number of days between two days, ignoring the time of day.
  function daysBetween(from, to) {
    const first = new Date(from.getFullYear(), from.getMonth(), from.getDate());
    const second = new Date(to.getFullYear(), to.getMonth(), to.getDate());
    return Math.round((second - first) / 86400000);
  }

  function formatDate(text) {
    return parseDate(text).toLocaleDateString(undefined, {
      weekday: "long",
      month: "long",
      day: "numeric",
      year: "numeric",
    });
  }

  function weekLabel(date) {
    const start = startOfWeek(date);
    const end = addDays(start, 6);
    return `${MONTHS[start.getMonth()]} ${start.getDate()} – ${MONTHS[end.getMonth()]} ${end.getDate()}, ${end.getFullYear()}`;
  }

  // ----- State ----- //

  function loadSnap() {
    try {
      const stored = localStorage.getItem(SNAP_KEY);
      if (stored === null) return 60;

      const value = Number(stored);
      return Number.isFinite(value) && value >= 0 && value <= 100 ? value : 60;
    } catch {
      return 60;
    }
  }

  function createState(element) {
    return {
      element,
      status: element.querySelector(".scheduler__status"),
      content: element.querySelector(".scheduler__content"),
      track: element.querySelector(".scheduler__track"),
      months: element.querySelector(".scheduler__months"),
      period: element.querySelector(".scheduler__period"),
      dateInput: element.querySelector(".scheduler__date"),
      scheduleButton: element.querySelector(".scheduler__schedule"),
      selectionText: element.querySelector(".scheduler__selection"),
      snapSlider: element.querySelector(".scheduler__snap-slider"),
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
      snap: loadSnap(),
      start: new Date(),
      monthStart: new Date(),
      monthCount: MONTH_UNITS,
      pitch: DAY_WIDTH,
      shifting: false,
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

    for (const entry of state.content.querySelectorAll(".scheduler__entry")) {
      entry.classList.toggle("is-selected", selected.has(entry.dataset.path));
    }
    for (const column of state.content.querySelectorAll(".scheduler__column")) {
      column.classList.toggle("is-selected", state.selectedDays.has(column.dataset.date));
    }
    for (const row of state.content.querySelectorAll(".scheduler__weekday")) {
      row.classList.toggle("is-selected", state.selectedDays.has(row.dataset.date));
    }
    for (const cell of state.content.querySelectorAll(".scheduler__month-day")) {
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

  // One column of the day view.
  function buildDayColumn(date) {
    const dateText = isoDate(date);

    const column = document.createElement("section");
    column.className = "scheduler__column";
    column.dataset.date = dateText;
    column.style.width = `${DAY_WIDTH}px`;
    if (dateText === isoDate(new Date())) column.classList.add("is-today");

    const header = document.createElement("header");
    header.className = "scheduler__column-header";

    const weekday = document.createElement("span");
    weekday.className = "scheduler__column-weekday";
    weekday.textContent = WEEKDAYS[date.getDay()];

    const number = document.createElement("span");
    number.className = "scheduler__column-date";
    number.textContent = String(date.getDate());

    const month = document.createElement("span");
    month.className = "scheduler__column-month";
    month.textContent = MONTHS[date.getMonth()];

    header.append(weekday, number, month);
    header.addEventListener("click", () => toggleDay(dateText));

    const body = document.createElement("div");
    body.className = "scheduler__column-body";
    for (const recipe of recipesOn(dateText)) body.append(buildEntry(recipe, dateText));

    column.append(header, body);
    return column;
  }

  // One column of the week view.
  function buildWeekColumn(date) {
    const column = document.createElement("section");
    column.className = "scheduler__column";
    column.dataset.date = isoDate(date);
    column.style.width = `${WEEK_WIDTH}px`;

    const header = document.createElement("header");
    header.className = "scheduler__column-header";

    const range = document.createElement("span");
    range.className = "scheduler__column-range";
    range.textContent = weekLabel(date);
    header.append(range);

    const body = document.createElement("div");
    body.className = "scheduler__column-body";

    for (let index = 0; index < 7; index += 1) {
      const day = addDays(date, index);
      const dateText = isoDate(day);

      const row = document.createElement("div");
      row.className = "scheduler__weekday";
      row.dataset.date = dateText;
      if (dateText === isoDate(new Date())) row.classList.add("is-today");

      const name = document.createElement("span");
      name.className = "scheduler__weekday-name";
      name.textContent = `${WEEKDAYS[day.getDay()]} ${day.getDate()}`;
      name.addEventListener("click", () => toggleDay(dateText));

      row.append(name);
      for (const recipe of recipesOn(dateText)) row.append(buildEntry(recipe, dateText, true));

      body.append(row);
    }

    column.append(header, body);
    return column;
  }

  // One month of the month view.
  function buildMonth(date) {
    const month = document.createElement("section");
    month.className = "scheduler__month";
    month.dataset.month = isoDate(new Date(date.getFullYear(), date.getMonth(), 1));

    const header = document.createElement("h4");
    header.className = "scheduler__month-header";
    header.textContent = `${MONTHS[date.getMonth()]} ${date.getFullYear()}`;

    const weekdays = document.createElement("div");
    weekdays.className = "scheduler__weekdays";
    for (const name of WEEKDAYS) {
      const label = document.createElement("span");
      label.textContent = name;
      weekdays.append(label);
    }

    const grid = document.createElement("div");
    grid.className = "scheduler__month-grid";

    const start = startOfWeek(new Date(date.getFullYear(), date.getMonth(), 1));

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

    month.append(header, weekdays, grid);
    return month;
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
  const unitCount = () => (state.view === "week" ? WEEK_UNITS : DAY_UNITS);

  // The distance between two columns, measured from the rendered ones.
  function measurePitch() {
    const first = state.track.firstElementChild;
    if (!first) return 0;

    const gap = parseFloat(getComputedStyle(state.track).columnGap) || 0;
    return first.offsetWidth + gap;
  }

  function unitIndex(date) {
    const days = daysBetween(state.start, date);
    return state.view === "week" ? Math.floor(days / 7) : days;
  }

  function renderTrack() {
    const fragment = document.createDocumentFragment();
    for (let index = 0; index < unitCount(); index += 1) {
      fragment.append(buildUnit(addDays(state.start, index * unitDays())));
    }

    state.track.replaceChildren(fragment);
    state.pitch = measurePitch();
    refreshSelection();
  }

  function buildUnit(date) {
    return state.view === "week" ? buildWeekColumn(date) : buildDayColumn(date);
  }

  // Puts the focused date in the middle of the track.
  function centerTrack() {
    if (!state.pitch) return;
    const offset =
      unitIndex(state.date) * state.pitch - state.track.clientWidth / 2 + state.pitch / 2;
    state.track.scrollLeft = Math.max(0, offset);
  }

  // Moves the window so the focused date sits in the middle of it.
  function resetWindow() {
    const units = Math.floor(unitCount() / 2);
    const anchor = state.view === "week" ? startOfWeek(state.date) : state.date;
    state.start = addDays(anchor, -units * unitDays());
  }

  // Grows the window at one end so the view never runs out of days. The
  // units are added and removed at the far ends, so the days that are in
  // view stay where they are.
  function shiftWindow(direction) {
    if (state.shifting) return;
    state.shifting = true;
    window.setTimeout(() => {
      state.shifting = false;
    }, 60);

    const units = Math.floor(unitCount() / 2);
    const fragment = document.createDocumentFragment();

    if (direction < 0) {
      const start = addDays(state.start, -units * unitDays());
      for (let index = 0; index < units; index += 1) {
        fragment.append(buildUnit(addDays(start, index * unitDays())));
      }

      state.track.prepend(fragment);
      state.start = start;
      // The days that were in view moved to the right.
      state.track.scrollLeft += units * state.pitch;
      trimTrack("right");
      return;
    }

    for (let index = 0; index < units; index += 1) {
      fragment.append(buildUnit(addDays(state.start, (unitCount() + index) * unitDays())));
    }

    state.track.append(fragment);
    trimTrack("left");
  }

  // Removes the units that fell out of the window at the far end.
  function trimTrack(side) {
    const units = Math.floor(unitCount() / 2);

    for (let index = 0; index < units; index += 1) {
      const element =
        side === "right" ? state.track.lastElementChild : state.track.firstElementChild;
      if (!element) break;

      element.remove();

      if (side === "left") {
        state.start = addDays(state.start, unitDays());
        // The days that were in view moved to the left.
        state.track.scrollLeft -= state.pitch;
      }
    }
  }

  function renderMonths() {
    const anchor = new Date(state.date.getFullYear(), state.date.getMonth(), 1);
    state.monthStart = addMonths(anchor, -Math.floor(MONTH_UNITS / 2));
    state.monthCount = MONTH_UNITS;

    const fragment = document.createDocumentFragment();
    for (let index = 0; index < MONTH_UNITS; index += 1) {
      fragment.append(buildMonth(addMonths(state.monthStart, index)));
    }

    state.months.replaceChildren(fragment);
    refreshSelection();
    centerMonths();
  }

  function centerMonths() {
    const anchor = new Date(state.date.getFullYear(), state.date.getMonth(), 1);
    const month = state.months.querySelector(`[data-month="${isoDate(anchor)}"]`);
    if (month) state.months.scrollTop = month.offsetTop;
  }

  // Grows the month list at one end so the view never runs out of months.
  function extendMonths(direction) {
    if (direction < 0) {
      const month = buildMonth(addMonths(state.monthStart, -1));
      state.months.prepend(month);
      state.monthStart = addMonths(state.monthStart, -1);
      state.monthCount += 1;
      // Keep the month that was in view where it is.
      state.months.scrollTop += month.offsetHeight;
      return;
    }

    state.months.append(buildMonth(addMonths(state.monthStart, state.monthCount)));
    state.monthCount += 1;
  }

  function renderCalendar() {
    if (state.view === "month") {
      // The sideways views are not used in the month view, so their days
      // are dropped instead of lingering in the page.
      state.track.replaceChildren();
      renderMonths();
      return;
    }

    state.months.replaceChildren();
    resetWindow();
    renderTrack();
    centerTrack();
  }

  // ----- Scrolling and snapping ----- //

  function onTrackScroll() {
    if (!state.pitch) return;

    // The window grows when the view reaches either end of the track.
    const left = Math.floor(state.track.scrollLeft / state.pitch);
    const right = Math.floor((state.track.scrollLeft + state.track.clientWidth) / state.pitch);

    if (!state.shifting) {
      if (left <= 0) {
        shiftWindow(-1);
      } else if (right >= unitCount() - 1) {
        shiftWindow(1);
      }
    }

    updateFocusedDate();
    scheduleSnap();
  }

  function onMonthsScroll() {
    const first = state.months.firstElementChild;
    const last = state.months.lastElementChild;
    if (!first || !last) return;

    if (state.months.scrollTop < first.offsetTop + EDGE) {
      extendMonths(-1);
    } else if (
      state.months.scrollTop + state.months.clientHeight >
      state.months.scrollHeight - EDGE
    ) {
      extendMonths(1);
    }
  }

  // The date in the middle of the track is the one the view is about.
  function updateFocusedDate() {
    if (!state.pitch) return;

    const index = Math.round((state.track.scrollLeft + state.track.clientWidth / 2) / state.pitch);
    const day = addDays(state.start, index * unitDays());
    if (isoDate(day) === isoDate(state.date)) return;

    state.date = day;
    renderPeriod();
    if (document.activeElement !== state.dateInput) state.dateInput.value = isoDate(day);
  }

  function scheduleSnap() {
    window.clearTimeout(snapTimer);
    snapTimer = window.setTimeout(snapTrack, 260);
  }

  // Pulls the track to the nearest column. The snap intensity decides how
  // hard the track is pulled, so a low setting glides and a high one snaps.
  function snapTrack() {
    const intensity = state.snap / 100;
    if (intensity <= 0 || !state.pitch) return;

    const offset = state.track.scrollLeft;
    const target = Math.round(offset / state.pitch) * state.pitch;
    if (Math.abs(target - offset) < 1) return;

    glideTo(target, intensity);
  }

  function glideTo(target, intensity) {
    window.cancelAnimationFrame(glideFrame);

    const step = () => {
      const difference = target - state.track.scrollLeft;
      // The last step is set outright: the browser keeps the scroll
      // position on whole pixels, so a smaller step would never arrive.
      if (Math.abs(difference) <= 2) {
        state.track.scrollLeft = target;
        glideFrame = 0;
        return;
      }

      state.track.scrollLeft = Math.round(
        state.track.scrollLeft + difference * (0.06 + 0.26 * intensity),
      );
      glideFrame = window.requestAnimationFrame(step);
    };

    glideFrame = window.requestAnimationFrame(step);
  }

  // ----- Navigation ----- //

  function setView(view) {
    state.view = view;
    state.element.classList.toggle("scheduler--month", view === "month");

    for (const button of state.element.querySelectorAll("[data-scheduler-view]")) {
      button.setAttribute("aria-pressed", String(button.dataset.schedulerView === view));
    }

    renderPeriod();
    renderCalendar();
  }

  function step(amount) {
    if (state.view === "month") {
      state.date = addMonths(state.date, amount);
    } else {
      state.date = addDays(state.date, amount * unitDays());
    }

    state.dateInput.value = isoDate(state.date);
    renderPeriod();
    renderCalendar();
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
    renderCalendar();
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
    renderCalendar();
    refreshSelection();
  }

  async function unschedule(recipe, dateText) {
    const dates = recipe.dates.filter((date) => date !== dateText);
    const saved = await saveDates(recipe.path, dates);
    if (!saved) return;

    recipe.dates = saved;
    setStatus(`Removed ${recipe.title} from ${formatDate(dateText)}.`);
    renderCalendar();
    refreshSelection();
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
      renderCalendar();
    });

    element.querySelector(".scheduler__select")?.addEventListener("click", () => {
      setMode(state.mode === "day" ? "recipe" : "day");
    });

    element.querySelector(".scheduler__schedule")?.addEventListener("click", () => {
      if (state.mode === "day") unscheduleSelectedDays();
      else scheduleSelected();
    });

    // The snap intensity decides how hard the track snaps to a column.
    element.querySelector(".scheduler__snap-slider")?.addEventListener("input", (event) => {
      state.snap = Number(event.target.value);
      try {
        localStorage.setItem(SNAP_KEY, String(state.snap));
      } catch {
        // A browser without storage keeps the setting for this session only.
      }
    });

    // Picking a date moves the calendar to that day.
    element.querySelector(".scheduler__date")?.addEventListener("change", (event) => {
      if (!event.target.value) return;
      state.date = parseDate(event.target.value);
      renderPeriod();
      renderCalendar();
    });

    state.track?.addEventListener("scroll", onTrackScroll, { passive: true });
    state.months?.addEventListener("scroll", onMonthsScroll, { passive: true });

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
        state.snapSlider.value = String(state.snap);
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
      renderCalendar();
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
