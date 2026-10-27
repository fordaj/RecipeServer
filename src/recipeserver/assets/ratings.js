(() => {
  const root = document.querySelector("#recipe-ratings");
  if (!root) return;

  const form = root.querySelector("#recipe-rating-form");
  const addButton = root.querySelector(".recipe-ratings__add");
  const cancelButton = root.querySelector("#cancel-rating");
  const saveButton = root.querySelector("#save-rating");
  const authorInput = root.querySelector("#rating-author");
  const scoreInput = root.querySelector("#rating-score");
  const scoreValue = root.querySelector("#rating-score-value");
  const status = root.querySelector("#rating-status");
  const list = root.querySelector("#rating-list");
  const recipePath = getMarkdownPath();

  function getMarkdownPath() {
    const page = decodeURIComponent(window.location.pathname.replace(/^\/+/, ""));
    return page.replace(/\.html$/i, ".md");
  }

  function normalizedName(name) {
    return name.trim().normalize("NFKC").toLowerCase();
  }

  function createRatingId() {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }

    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (character) => {
      const random = (Math.random() * 16) | 0;
      const value = character === "x" ? random : (random & 0x3) | 0x8;
      return value.toString(16);
    });
  }

  async function getRatings() {
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

  function getInitials(name) {
    return name
      .split(/\s+/)
      .filter(Boolean)
      .map((part) => part[0].toUpperCase())
      .join("");
  }

  function getRatingLabel(rating) {
    return `${rating / 2} out of 5 stars (${rating} out of 10)`;
  }

  function parseRating(input) {
    const value = input.value.trim();
    const isValidFormat = /^(?:\d+(?:\.\d*)?|\.\d+)$/.test(value);
    const rating = isValidFormat ? Number(value) : NaN;
    const isValid = Number.isFinite(rating) && rating >= 0 && rating <= 10;

    input.setCustomValidity(isValid || !value ? "" : "Enter a number from 0 to 10.");
    return isValid ? rating : null;
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

  function createDate(timestamp) {
    const dateElement = document.createElement("time");
    dateElement.className = "recipe-rating__date";
    dateElement.dateTime = timestamp;

    const date = new Date(timestamp);
    dateElement.textContent = Number.isNaN(date.getTime())
      ? timestamp
      : date.toLocaleDateString(undefined, {
          year: "numeric",
          month: "long",
          day: "numeric",
        });

    return dateElement;
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

    const average = ratings.reduce((total, item) => total + Number(item.rating), 0) / ratings.length;
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
    const sortedRatings = [...ratings].sort((a, b) => {
      const timestampA = Date.parse(a.updated || a.created) || 0;
      const timestampB = Date.parse(b.updated || b.created) || 0;
      return timestampB - timestampA;
    });

    list.replaceChildren(...sortedRatings.map(createRating));
    updateAverage(ratings);
  }

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

  function updateScorePreview(input, preview, meter) {
    const score = parseRating(input);

    if (score === null) {
      preview.textContent = "—/10";
      meter.style.setProperty("--rating-fill", "0%");
      meter.setAttribute("aria-label", "Enter a rating from 0 to 10");
      return;
    }

    preview.textContent = `${score}/10`;
    meter.style.setProperty("--rating-fill", `${(score / 10) * 100}%`);
    meter.setAttribute("aria-label", getRatingLabel(score));
  }

  function createEditForm(article, rating) {
    const content = article.querySelector(".recipe-rating__content");
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

    const scoreInput = document.createElement("input");
    scoreInput.type = "text";
    scoreInput.inputMode = "decimal";
    scoreInput.maxLength = 16;
    scoreInput.required = true;
    scoreInput.value = String(rating.rating);
    scoreInput.setAttribute("aria-label", "Rating out of 10");

    const meter = createStarMeter(Number(rating.rating));
    const score = document.createElement("output");
    score.className = "recipe-rating__score";

    updateScorePreview(scoreInput, score, meter);
    scoreInput.addEventListener("input", () => updateScorePreview(scoreInput, score, meter));
    scoreLine.append(scoreInput, meter, score);

    const actions = document.createElement("div");
    actions.className = "recipe-rating__actions recipe-rating__form-actions";

    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "Cancel";

    const save = document.createElement("button");
    save.type = "submit";
    save.textContent = "Save";

    const message = document.createElement("p");
    message.className = "recipe-rating__status";
    message.setAttribute("role", "status");

    actions.append(cancel, save);
    editForm.append(nameInput, scoreLine, actions, message);
    content.replaceChildren(editForm);

    cancel.addEventListener("click", () => article.replaceWith(createRating(rating)));
    editForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const name = nameInput.value.trim();
      const scoreValue = parseRating(scoreInput);

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

        if (latest.some((item) => item.id !== rating.id && normalizedName(item.name) === normalizedName(name))) {
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

    nameInput.focus();
  }

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
      const ratings = await getRatings();
      renderAllRatings(ratings);
    } catch (error) {
      console.error("Unable to load ratings:", error);
      status.textContent = "Unable to load ratings.";
    }
  }

  addButton.addEventListener("click", () => {
    form.reset();
    scoreInput.value = "5";
    updateScorePreview(scoreInput, scoreValue, form.querySelector(".recipe-rating__stars"));
    setFormOpen(true);
  });

  cancelButton.addEventListener("click", () => {
    form.reset();
    setFormOpen(false);
  });

  scoreInput.addEventListener("input", () => {
    updateScorePreview(scoreInput, scoreValue, form.querySelector(".recipe-rating__stars"));
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = authorInput.value.trim();
    const ratingValue = parseRating(scoreInput);

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
      const updatedRatings = [
        ...ratings,
        {
          name,
          created: timestamp,
          updated: timestamp,
          id: createRatingId(),
          rating: ratingValue,
        },
      ];

      await saveRatings(updatedRatings);
      renderAllRatings(updatedRatings);
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
        createEditForm(article, rating);
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
