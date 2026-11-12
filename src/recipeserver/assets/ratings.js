(() => {
  const root = document.querySelector("#recipe-ratings");
  if (!root) return;

  // ----- DOM references ----- //
  const form = root.querySelector("#recipe-rating-form");
  const addButton = root.querySelector(".recipe-ratings__add");
  const cancelButton = root.querySelector("#cancel-rating");
  const saveButton = root.querySelector("#save-rating");
  const authorInput = root.querySelector("#rating-author");
  const scoreInput = root.querySelector("#rating-score");
  const scoreValue = root.querySelector("#rating-score-value");
  const status = root.querySelector("#rating-status");
  const list = root.querySelector("#rating-list");
  const helpers = window.RecipeFeedback || {};
  const recipePath = (helpers.getMarkdownPath || getMarkdownPathFallback)();

  // Each star is worth two points, so every half star is worth one point and
  // the lowest score the slider can set is 1.
  const STAR_COUNT = 5;
  const MIN_SLIDER_SCORE = 1;
  const MAX_SLIDER_SCORE = 10;

  function getMarkdownPathFallback() {
    const page = decodeURIComponent(window.location.pathname.replace(/^\/+/, ""));
    return page.replace(/\.html$/i, ".md");
  }

  // ----- Data helpers ----- //
  function normalizedName(name) {
    return String(name || "")
      .trim()
      .normalize("NFKC")
      .toLowerCase();
  }

  function createRatingId() {
    return helpers.createId ? helpers.createId() : `rating-${Date.now()}`;
  }

  async function getRatings() {
    if (helpers.fetchMetadata) {
      return helpers.fetchMetadata("ratings", recipePath);
    }
    const params = new URLSearchParams({ path: recipePath });
    const response = await fetch(`/api/metadata/ratings?${params}`);
    if (!response.ok) {
      throw new Error(`Failed to load ratings (HTTP ${response.status})`);
    }
    const data = await response.json();
    if (!Array.isArray(data.value)) {
      throw new Error("Invalid ratings response");
    }
    return data.value;
  }

  async function saveRatings(ratings) {
    if (helpers.saveMetadata) {
      return helpers.saveMetadata("ratings", recipePath, ratings);
    }
    const response = await fetch("/api/metadata/ratings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: recipePath, value: ratings }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.success !== true) {
      throw new Error(result.error || `Unable to save ratings (HTTP ${response.status})`);
    }
  }

  // ----- Rating value parsing ----- //
  function parseRatingText(text) {
    const value = String(text ?? "").trim();
    if (!value) {
      return null;
    }
    const isValidFormat = /^(?:\d+(?:\.\d*)?|\.\d+)$/.test(value);
    const rating = isValidFormat ? Number(value) : NaN;
    return Number.isFinite(rating) && rating >= 0 && rating <= 10 ? rating : null;
  }

  function validateRatingInput(input) {
    const value = String(input.value ?? "").trim();
    const parsed = parseRatingText(value);
    input.setCustomValidity(parsed !== null || !value ? "" : "Enter a number from 0 to 10.");
    return parsed;
  }

  function getRatingLabel(rating) {
    return `${rating / 2} out of 5 stars (${rating} out of 10)`;
  }

  // ----- Number field ----- //
  function selectAllOnClick(input) {
    // Clicking the score field highlights the whole score so typing replaces it.
    input.addEventListener("click", () => input.select());
    input.addEventListener("focus", () => {
      // The browser places the caret once the field is focused, so the score is
      // highlighted on the next tick instead of during the focus event.
      setTimeout(() => input.select(), 0);
    });
  }

  // ----- Rating slider ----- //
  function updateStarSlider(slider, score) {
    const value = score === null ? 0 : score;
    slider.style.setProperty("--rating-fill", `${(value / 10) * 100}%`);
    slider.setAttribute(
      "aria-valuenow",
      String(Math.min(Math.max(value, MIN_SLIDER_SCORE), MAX_SLIDER_SCORE)),
    );
    slider.setAttribute("aria-valuetext", score === null ? "No rating" : `${value} out of 10`);
  }

  // Each star holds two scores, one for its left half and one for its right
  // half, so a click anywhere on the slider lands on a whole or half star.
  function scoreFromPointer(slider, clientX) {
    const rect = slider.getBoundingClientRect();
    if (!rect.width) return MIN_SLIDER_SCORE;

    const ratio = (clientX - rect.left) / rect.width;
    const star = Math.min(Math.max(Math.floor(ratio * STAR_COUNT), 0), STAR_COUNT - 1);
    const half = ratio * STAR_COUNT - star;
    return 2 * star + (half < 0.5 ? 1 : 2);
  }

  function createStarSlider(score, onChange) {
    const slider = document.createElement("span");
    slider.className = "recipe-rating__stars recipe-rating__stars--slider";
    slider.setAttribute("role", "slider");
    slider.setAttribute("aria-label", "Rating out of 10");
    slider.setAttribute("aria-valuemin", String(MIN_SLIDER_SCORE));
    slider.setAttribute("aria-valuemax", String(MAX_SLIDER_SCORE));
    slider.tabIndex = 0;

    for (let index = 0; index < STAR_COUNT; index += 1) {
      const star = document.createElement("span");
      star.className = "recipe-rating__star";
      star.textContent = "★";
      slider.append(star);
    }

    let currentScore = score;

    function setScore(nextScore) {
      currentScore = nextScore;
      updateStarSlider(slider, nextScore);
    }

    function applyScore(nextScore) {
      const clamped = Math.min(Math.max(nextScore, MIN_SLIDER_SCORE), MAX_SLIDER_SCORE);
      setScore(clamped);
      onChange(clamped);
    }

    slider.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      slider.focus();
      slider.setPointerCapture(event.pointerId);
      applyScore(scoreFromPointer(slider, event.clientX));
    });

    slider.addEventListener("pointermove", (event) => {
      if (!slider.hasPointerCapture(event.pointerId)) return;
      applyScore(scoreFromPointer(slider, event.clientX));
    });

    const releasePointer = (event) => {
      if (slider.hasPointerCapture(event.pointerId)) {
        slider.releasePointerCapture(event.pointerId);
      }
    };
    slider.addEventListener("pointerup", releasePointer);
    slider.addEventListener("pointercancel", releasePointer);

    slider.addEventListener("keydown", (event) => {
      const base = Math.round(currentScore);
      let next = null;
      if (event.key === "ArrowRight" || event.key === "ArrowUp") {
        next = base + 1;
      } else if (event.key === "ArrowLeft" || event.key === "ArrowDown") {
        next = base - 1;
      } else if (event.key === "PageUp") {
        next = base + 2;
      } else if (event.key === "PageDown") {
        next = base - 2;
      } else if (event.key === "Home") {
        next = MIN_SLIDER_SCORE;
      } else if (event.key === "End") {
        next = MAX_SLIDER_SCORE;
      } else {
        return;
      }

      event.preventDefault();
      applyScore(next);
    });

    setScore(score);
    return { slider, setScore };
  }

  // ----- Rendering ----- //
  function getInitials(name) {
    return helpers.getInitials
      ? helpers.getInitials(name)
      : String(name || "")
          .slice(0, 2)
          .toUpperCase();
  }

  function createDate(timestamp) {
    if (helpers.createDateElement) {
      return helpers.createDateElement(timestamp, "recipe-rating__date");
    }
    const dateElement = document.createElement("time");
    dateElement.className = "recipe-rating__date";
    if (timestamp) dateElement.dateTime = timestamp;
    dateElement.textContent = String(timestamp || "");
    return dateElement;
  }

  function createStarMeter(rating) {
    const meter = document.createElement("span");
    meter.className = "recipe-rating__stars";
    meter.setAttribute("role", "img");
    meter.setAttribute("aria-label", getRatingLabel(rating));
    meter.style.setProperty("--rating-fill", `${(rating / 10) * 100}%`);
    meter.textContent = "★★★★★";
    return meter;
  }

  function updateScorePreview(input, preview, renderStars) {
    const score = parseRatingText(input.value);
    validateRatingInput(input);
    renderStars(score);

    if (score === null) {
      preview.textContent = "—/10";
      return;
    }

    preview.textContent = `${score}/10`;
  }

  function updateAverage(ratings) {
    const primary = document.querySelector(".recipe-overview__primary");
    if (!primary) return;

    let summary = primary.querySelector(".recipe-overview__rating");
    if (ratings.length === 0) {
      summary?.remove();
      return;
    }

    if (!summary) {
      summary = document.createElement("span");
      summary.className = "recipe-overview__rating";
      primary.prepend(summary);
    }

    const average =
      ratings.reduce((total, item) => total + Number(item.rating), 0) / ratings.length;
    summary.textContent = `★ ${average.toFixed(1)}/10`;
  }

  function createRating(rating) {
    const article = document.createElement("article");
    article.className = "recipe-rating";
    article.dataset.ratingId = rating.id;

    const name = (rating.name || "Anonymous").trim() || "Anonymous";
    const avatar = document.createElement("div");
    avatar.className = "recipe-rating__avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = getInitials(name);

    const content = document.createElement("div");
    content.className = "recipe-rating__content";

    const meta = document.createElement("header");
    meta.className = "recipe-rating__meta";

    const author = document.createElement("span");
    author.className = "recipe-rating__author";
    author.textContent = name;
    meta.append(author, createDate(rating.updated || rating.created));

    const meter = createStarMeter(Number(rating.rating));
    const score = document.createElement("span");
    score.className = "recipe-rating__score";
    score.textContent = `${rating.rating}/10`;

    const actions = document.createElement("div");
    actions.className = "recipe-rating__actions";
    for (const [action, label] of [
      ["edit", "Edit"],
      ["delete", "Remove"],
    ]) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.action = action;
      button.textContent = label;
      actions.append(button);
    }

    const meterLine = document.createElement("div");
    meterLine.className = "recipe-rating__meter";
    meterLine.append(meter, score, actions);

    content.append(meta, meterLine);
    article.append(avatar, content);
    return article;
  }

  function renderAllRatings(ratings) {
    const sort = helpers.sortByUpdatedDesc || ((items) => [...items]);
    list.replaceChildren(...sort(ratings).map(createRating));
    root.classList.toggle("is-empty", ratings.length === 0);
    updateAverage(ratings);
  }

  // ----- Form controls ----- //
  function setFormOpen(open) {
    form.hidden = !open;
    addButton.setAttribute("aria-expanded", String(open));
    status.textContent = "";
    if (open) authorInput.focus();
  }

  function setBusy(container, busy) {
    container.querySelectorAll("button, input").forEach((element) => {
      element.disabled = busy;
    });
  }

  // ----- Edit form ----- //
  function buildEditForm(rating) {
    const editForm = document.createElement("form");
    editForm.className = "recipe-rating__edit";

    const nameInput = document.createElement("input");
    nameInput.className = "recipe-rating__author-input";
    nameInput.value = rating.name;
    nameInput.maxLength = 100;
    nameInput.required = true;
    nameInput.setAttribute("aria-label", "Rating name");

    const scoreLine = document.createElement("div");
    scoreLine.className = "recipe-rating__meter";

    const editScoreInput = document.createElement("input");
    editScoreInput.type = "text";
    editScoreInput.inputMode = "decimal";
    editScoreInput.maxLength = 16;
    editScoreInput.required = true;
    editScoreInput.value = String(rating.rating);
    editScoreInput.setAttribute("aria-label", "Rating out of 10");

    const score = document.createElement("output");
    score.className = "recipe-rating__score";

    const { slider: editSlider, setScore: setEditScore } = createStarSlider(
      Number(rating.rating),
      (nextScore) => {
        editScoreInput.value = String(nextScore);
        updateScorePreview(editScoreInput, score, (value) => setEditScore(value));
      },
    );

    selectAllOnClick(editScoreInput);
    updateScorePreview(editScoreInput, score, (value) => setEditScore(value));
    editScoreInput.addEventListener("input", () =>
      updateScorePreview(editScoreInput, score, (value) => setEditScore(value)),
    );
    scoreLine.append(editScoreInput, editSlider, score);

    const actions = document.createElement("div");
    actions.className = "recipe-rating__actions recipe-rating__form-actions";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "Cancel";
    const save = document.createElement("button");
    save.type = "submit";
    save.textContent = "Save";
    actions.append(cancel, save);

    const message = document.createElement("p");
    message.className = "recipe-rating__status";
    message.setAttribute("role", "status");

    editForm.append(nameInput, scoreLine, actions, message);
    return { editForm, nameInput, scoreInput: editScoreInput, cancel, message };
  }

  function submitEditRating({
    editForm,
    article,
    rating,
    nameInput,
    scoreInput: editScoreInput,
    message,
  }) {
    editForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const name = nameInput.value.trim();
      const scoreValue = validateRatingInput(editScoreInput);

      if (!name || scoreValue === null) {
        editForm.reportValidity();
        return;
      }

      setBusy(editForm, true);
      try {
        const latest = await getRatings();
        const index = latest.findIndex((item) => item.id === rating.id);
        if (index === -1) {
          throw new Error("Rating no longer exists. Reload the page.");
        }
        if (
          latest.some(
            (item) => item.id !== rating.id && normalizedName(item.name) === normalizedName(name),
          )
        ) {
          throw new Error("A rating from this name already exists.");
        }

        latest[index] = {
          ...latest[index],
          name,
          rating: scoreValue,
          updated: new Date().toISOString(),
        };
        await saveRatings(latest);
        renderAllRatings(latest);
      } catch (error) {
        console.error("Unable to edit rating:", error);
        setBusy(editForm, false);
        message.textContent = error.message || "Unable to save this rating.";
      }
    });
  }

  function openEditForm(article, rating) {
    const content = article.querySelector(".recipe-rating__content");
    const controls = buildEditForm(rating);
    content.replaceChildren(controls.editForm);

    controls.cancel.addEventListener("click", () => article.replaceWith(createRating(rating)));
    submitEditRating({ article, rating, ...controls });
    controls.nameInput.focus();
  }

  // ----- Mutations ----- //
  async function deleteRating(article) {
    if (!window.confirm("Remove this rating? This cannot be undone.")) return;

    setBusy(article, true);
    try {
      const ratings = await getRatings();
      const index = ratings.findIndex((rating) => rating.id === article.dataset.ratingId);
      if (index === -1) {
        throw new Error("Rating no longer exists.");
      }
      ratings.splice(index, 1);
      await saveRatings(ratings);
      renderAllRatings(ratings);
    } catch (error) {
      console.error("Unable to remove rating:", error);
      setBusy(article, false);
      window.alert(error.message || "Unable to remove this rating.");
    }
  }

  async function loadRatings() {
    try {
      renderAllRatings(await getRatings());
    } catch (error) {
      console.error("Unable to load ratings:", error);
      status.textContent = "Unable to load ratings.";
    }
  }

  // ----- Event wiring ----- //
  const formStars = form.querySelector(".recipe-rating__stars");
  const { slider: formSlider, setScore: setFormScore } = createStarSlider(5, (nextScore) => {
    scoreInput.value = String(nextScore);
    updateScorePreview(scoreInput, scoreValue, (value) => setFormScore(value));
  });
  formStars?.replaceWith(formSlider);

  selectAllOnClick(scoreInput);

  addButton.addEventListener("click", () => {
    form.reset();
    scoreInput.value = "5";
    updateScorePreview(scoreInput, scoreValue, (value) => setFormScore(value));
    setFormOpen(true);
  });

  cancelButton.addEventListener("click", () => {
    form.reset();
    setFormOpen(false);
  });

  scoreInput.addEventListener("input", () => {
    updateScorePreview(scoreInput, scoreValue, (value) => setFormScore(value));
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = authorInput.value.trim();
    const ratingValue = validateRatingInput(scoreInput);

    if (!name) {
      status.textContent = "Please enter your name.";
      form.reportValidity();
      return;
    }
    if (ratingValue === null) {
      status.textContent = "Enter a rating from 0 to 10.";
      form.reportValidity();
      return;
    }

    saveButton.disabled = true;
    status.textContent = "Saving rating…";
    try {
      const ratings = await getRatings();
      if (ratings.some((rating) => normalizedName(rating.name) === normalizedName(name))) {
        throw new Error("A rating from this name already exists. Edit that rating instead.");
      }

      const timestamp = new Date().toISOString();
      await saveRatings([
        ...ratings,
        { name, created: timestamp, updated: timestamp, id: createRatingId(), rating: ratingValue },
      ]);
      renderAllRatings(await getRatings());
      form.reset();
      setFormOpen(false);
    } catch (error) {
      console.error("Unable to save rating:", error);
      status.textContent = error.message || "Unable to save your rating. Please try again.";
    } finally {
      saveButton.disabled = false;
    }
  });

  list.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button || !list.contains(button)) return;

    const article = button.closest(".recipe-rating");
    if (!article) return;

    if (button.dataset.action === "edit") {
      try {
        const ratings = await getRatings();
        const rating = ratings.find((item) => item.id === article.dataset.ratingId);
        if (!rating) throw new Error("Rating no longer exists. Reload the page.");
        openEditForm(article, rating);
      } catch (error) {
        console.error("Unable to edit rating:", error);
        window.alert(error.message || "Unable to edit this rating.");
      }
    } else if (button.dataset.action === "delete") {
      await deleteRating(article);
    }
  });

  loadRatings();
})();
