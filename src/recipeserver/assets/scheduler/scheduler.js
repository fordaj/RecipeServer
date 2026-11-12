(() => {
  const DIALOG_ID = "scheduler-dialog";
  const SCHEDULER_ASSETS = "/assets/scheduler";
  const SCHEDULER_API = "/api/scheduler";

  // The value of the option that schedules every recipe selected on the
  // index page.
  const SELECTED_OPTION = "__selected__";

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

  let dialog = null;
  let state = null;

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

  function formatDate(text) {
    return parseDate(text).toLocaleDateString(undefined, {
      weekday: "long",
      month: "long",
      day: "numeric",
      year: "numeric",
    });
  }

  // ----- State ----- //

  function createState(element) {
    return {
      element,
      status: element.querySelector(".scheduler__status"),
      content: element.querySelector(".scheduler__content"),
      period: element.querySelector(".scheduler__period"),
      recipeSelect: element.querySelector(".scheduler__recipe"),
      dateInput: element.querySelector(".scheduler__date"),
      recipes: [],
      byPath: new Map(),
      view: "day",
      date: new Date(),
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

  // Every scheduled recipe, oldest date first.
  function allEntries() {
    const entries = [];

    for (const recipe of state.recipes) {
      for (const date of recipe.dates) entries.push({ date, recipe });
    }

    entries.sort(
      (left, right) =>
        left.date.localeCompare(right.date) || left.recipe.title.localeCompare(right.recipe.title),
    );
    return entries;
  }

  // The recipes that are selected on the index page.
  function selectedPaths() {
    return [...document.querySelectorAll("#recipe-list .recipe-select__checkbox:checked")].map(
      (box) => box.dataset.path,
    );
  }

  function buildEmpty(message) {
    const empty = document.createElement("p");
    empty.className = "scheduler__empty";
    empty.textContent = message;
    return empty;
  }

  // ----- Rendering ----- //

  function buildEntry(entry) {
    const row = document.createElement("div");
    row.className = "scheduler__entry";

    if (entry.recipe.image) {
      const image = document.createElement("img");
      image.className = "scheduler__entry-image";
      image.src = entry.recipe.image;
      image.alt = "";
      image.loading = "lazy";
      row.append(image);
    }

    const text = document.createElement("div");
    text.className = "scheduler__entry-text";

    const link = document.createElement("a");
    link.className = "scheduler__entry-title";
    link.href = entry.recipe.url;
    link.textContent = entry.recipe.title;
    text.append(link);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "scheduler__remove";
    remove.setAttribute(
      "aria-label",
      `Remove ${entry.recipe.title} from ${formatDate(entry.date)}`,
    );
    remove.textContent = "×";
    remove.addEventListener("click", () => unschedule(entry));

    row.append(text, remove);
    return row;
  }

  // The single day view: an agenda of one day.
  function renderDay() {
    const date = isoDate(state.date);
    const list = document.createElement("div");
    list.className = "scheduler__entries";

    const recipes = recipesOn(date);
    if (!recipes.length) {
      list.append(buildEmpty("Nothing is scheduled for this day."));
      return list;
    }

    for (const recipe of recipes) list.append(buildEntry({ date, recipe }));
    return list;
  }

  // The multi day view: a month grid with every day side by side.
  function renderMonth() {
    const wrapper = document.createElement("div");
    wrapper.className = "scheduler__month-wrapper";

    const weekdays = document.createElement("div");
    weekdays.className = "scheduler__weekdays";
    for (const name of WEEKDAYS) {
      const label = document.createElement("span");
      label.textContent = name;
      weekdays.append(label);
    }

    const grid = document.createElement("div");
    grid.className = "scheduler__month";

    const first = new Date(state.date.getFullYear(), state.date.getMonth(), 1);
    const start = startOfWeek(first);
    const today = isoDate(new Date());

    for (let index = 0; index < 42; index += 1) {
      const day = addDays(start, index);
      const date = isoDate(day);

      const cell = document.createElement("div");
      cell.className = "scheduler__day";
      if (day.getMonth() !== state.date.getMonth()) cell.classList.add("scheduler__day--outside");
      if (date === today) cell.classList.add("scheduler__day--today");

      const number = document.createElement("button");
      number.type = "button";
      number.className = "scheduler__day-number";
      number.textContent = String(day.getDate());
      number.setAttribute("aria-label", `Show ${formatDate(date)}`);
      number.addEventListener("click", () => {
        state.date = day;
        state.dateInput.value = date;
        setView("day");
      });
      cell.append(number);

      for (const recipe of recipesOn(date)) {
        const chip = document.createElement("a");
        chip.className = "scheduler__chip";
        chip.href = recipe.url;
        chip.title = recipe.title;
        chip.textContent = recipe.title;
        cell.append(chip);
      }

      grid.append(cell);
    }

    wrapper.append(weekdays, grid);
    return wrapper;
  }

  // The list view: every scheduled recipe, grouped by date.
  function renderList() {
    const list = document.createElement("div");
    list.className = "scheduler__list";

    const entries = allEntries();
    if (!entries.length) {
      list.append(buildEmpty("No recipes are scheduled yet."));
      return list;
    }

    let currentDate = null;
    let items = null;

    for (const entry of entries) {
      if (entry.date !== currentDate) {
        currentDate = entry.date;

        const group = document.createElement("section");
        group.className = "scheduler__group";

        const heading = document.createElement("h4");
        heading.className = "scheduler__group-title";
        heading.textContent = formatDate(entry.date);

        items = document.createElement("div");
        items.className = "scheduler__entries";

        group.append(heading, items);
        list.append(group);
      }

      items.append(buildEntry(entry));
    }

    return list;
  }

  function renderPeriod() {
    const isList = state.view === "list";
    state.element.classList.toggle("scheduler--list", isList);

    if (isList) {
      const count = allEntries().length;
      state.period.textContent = `${count} scheduled recipe${count === 1 ? "" : "s"}`;
      return;
    }

    state.period.textContent =
      state.view === "day"
        ? formatDate(isoDate(state.date))
        : `${MONTHS[state.date.getMonth()]} ${state.date.getFullYear()}`;
  }

  function render() {
    renderPeriod();
    const view =
      state.view === "day" ? renderDay() : state.view === "multi" ? renderMonth() : renderList();
    state.content.replaceChildren(view);
  }

  // ----- Views and navigation ----- //

  function setView(view) {
    state.view = view;

    for (const button of state.element.querySelectorAll("[data-scheduler-view]")) {
      button.setAttribute("aria-pressed", String(button.dataset.schedulerView === view));
    }

    render();
  }

  function step(amount) {
    state.date = state.view === "day" ? addDays(state.date, amount) : addMonths(state.date, amount);
    state.dateInput.value = isoDate(state.date);
    render();
  }

  // ----- Scheduling ----- //

  function buildRecipeOptions() {
    const select = state.recipeSelect;
    select.replaceChildren();

    const selected = selectedPaths();
    if (selected.length) {
      const option = document.createElement("option");
      option.value = SELECTED_OPTION;
      option.textContent = `${selected.length} selected recipe${selected.length === 1 ? "" : "s"}`;
      select.append(option);
    }

    const group = document.createElement("optgroup");
    group.label = "All recipes";

    const recipes = [...state.recipes].sort((left, right) => left.title.localeCompare(right.title));
    for (const recipe of recipes) {
      const option = document.createElement("option");
      option.value = recipe.path;
      option.textContent = recipe.title;
      group.append(option);
    }

    select.append(group);
  }

  async function schedule() {
    const date = state.dateInput.value;
    if (!date) {
      setStatus("Choose a date first.");
      return;
    }

    const value = state.recipeSelect.value;
    const paths = value === SELECTED_OPTION ? selectedPaths() : value ? [value] : [];
    if (!paths.length) {
      setStatus("Choose a recipe to schedule.");
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
    render();
  }

  async function unschedule(entry) {
    const dates = entry.recipe.dates.filter((date) => date !== entry.date);
    const saved = await saveDates(entry.recipe.path, dates);
    if (!saved) return;

    entry.recipe.dates = saved;
    setStatus(`Removed ${entry.recipe.title} from ${formatDate(entry.date)}.`);
    render();
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
      render();
    });

    element.querySelector(".scheduler__schedule")?.addEventListener("click", schedule);

    // Picking a date moves the calendar to that day.
    element.querySelector(".scheduler__date")?.addEventListener("change", (event) => {
      if (!event.target.value) return;
      state.date = parseDate(event.target.value);
      render();
    });

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
      }

      if (!dialog.open) dialog.showModal();

      setStatus("Loading…");

      await loadSchedule();
      buildRecipeOptions();

      state.date = new Date();
      state.dateInput.value = isoDate(state.date);
      setView(state.view);
      setStatus("");
    } catch (error) {
      setStatus(error.message || "Unable to load the schedule.");
    }
  }

  function initialize() {
    document.querySelector("#scheduler")?.addEventListener("click", openScheduler);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }
})();
