(() => {
  // A dropdown backed metadata field. The dropdown offers the values that are
  // already used in the recipe library; "Add new" swaps the dropdown for a
  // text field so a value that is not in the library yet can still be typed
  // in. Multi-value fields collect several values, single-value fields keep
  // exactly one.
  //
  // Single-value "combo" fields (the feedback name pickers) skip the chip
  // row and the "Add new" swap: they render a plain text input whose value is
  // the current name, with the library dropdown next to it. Picking an option
  // writes the value into the input; typing works for any other value.

  const NEW_VALUE = "__new__";

  // The chip remove button uses the shared x.svg asset. It is fetched once
  // and reused for every chip; if it cannot be loaded the buttons fall back
  // to the "×" character.
  const X_ICON_URL = "/assets/x.svg";
  let xIconMarkup = null;
  const pendingXIconButtons = new Set();

  function applyXIcon(button) {
    if (xIconMarkup === null) {
      pendingXIconButtons.add(button);
      return;
    }
    if (xIconMarkup) {
      button.innerHTML = xIconMarkup;
    } else {
      button.textContent = "×";
    }
  }

  if (typeof window !== "undefined" && window.RecipeIcons?.loadSvgIcon) {
    window.RecipeIcons.loadSvgIcon(X_ICON_URL).then((svg) => {
      xIconMarkup = svg || "";
      for (const button of pendingXIconButtons) applyXIcon(button);
      pendingXIconButtons.clear();
    });
  } else {
    xIconMarkup = "";
  }

  const FIELDS = {
    meals: { label: "meal", mode: "multi" },
    categories: { label: "category", mode: "multi" },
    cuisine: { label: "cuisine", mode: "multi" },
    tags: { label: "tag", mode: "multi" },
    status: { label: "status", mode: "single" },
    contributor: { label: "contributor", mode: "single" },
    "source.author": { label: "source author", mode: "single" },
    "source.title": { label: "source title", mode: "single" },
    commenters: { label: "commenter", mode: "single", variant: "combo", placeholder: "Your name" },
    raters: { label: "rater", mode: "single", variant: "combo", placeholder: "Your name" },
  };

  function fieldConfig(field) {
    return FIELDS[field] ?? { label: field, mode: "single" };
  }

  function maxLengthFromDataset(element) {
    const maxLength = Number(element.dataset.maxLength);
    return Number.isFinite(maxLength) && maxLength > 0 ? maxLength : 0;
  }

  class MetadataPicker {
    constructor(element) {
      this.element = element;
      this.field = element.dataset.field;
      this.config = fieldConfig(this.field);
      this.label = this.config.label;
      this.multi = this.config.mode === "multi";
      this.combo = this.config.variant === "combo";
      this.options = [];
      this.values = [];
      this.disabled = false;

      this.controls = document.createElement("span");
      this.controls.className = "recipe-editor__picker-controls";

      this.select = document.createElement("select");
      this.select.className = "recipe-editor__picker-select field-input";
      this.select.setAttribute("aria-label", this.selectLabel());

      if (this.combo) {
        this.input = document.createElement("input");
        this.input.className = "recipe-editor__picker-input field-input";
        this.input.type = "text";
        const placeholder = this.config.placeholder ?? `New ${this.label}`;
        // The browser reflects the placeholder attribute onto the property.
        this.input.placeholder = placeholder;
        this.input.setAttribute("placeholder", placeholder);
        this.input.setAttribute("aria-label", placeholder);
        const maxLength = maxLengthFromDataset(element);
        if (maxLength) {
          this.input.maxLength = maxLength;
        }
        this.controls.append(this.input, this.select);
        this.element.append(this.controls);
        this.input.addEventListener("input", () => this.handleInput());
      } else {
        this.newInput = document.createElement("input");
        this.newInput.className = "recipe-editor__picker-new field-input";
        this.newInput.type = "text";
        this.newInput.placeholder = `New ${this.label}`;
        this.newInput.setAttribute("aria-label", `New ${this.label}`);
        this.newInput.hidden = true;
        const maxLength = maxLengthFromDataset(element);
        if (maxLength) {
          this.newInput.maxLength = maxLength;
        }

        this.addButton = document.createElement("button");
        this.addButton.type = "button";
        this.addButton.className = "recipe-editor__picker-add";
        this.addButton.textContent = "Add";
        this.addButton.hidden = true;

        this.valuesElement = document.createElement("span");
        this.valuesElement.className = "recipe-editor__picker-values";

        this.controls.append(this.select, this.newInput, this.addButton);
        this.element.append(this.controls, this.valuesElement);

        this.addButton.addEventListener("click", () => this.commitNewValue());
        this.newInput.addEventListener("keydown", (event) => this.handleNewInputKey(event));
      }

      this.select.addEventListener("change", () => this.handleSelectChange());

      this.render();
    }

    selectLabel() {
      return this.multi ? `Add ${this.label}` : `Select ${this.label}`;
    }

    // ----- Values ----- //

    focus() {
      if (this.combo) {
        this.input.focus();
        return;
      }
      this.select.focus();
    }

    getValues() {
      return [...this.values];
    }

    setValues(values) {
      const list = (Array.isArray(values) ? values : [])
        .map((value) => String(value ?? "").trim())
        .filter(Boolean);

      this.values = [];
      (this.multi ? list : list.slice(0, 1)).forEach((value) =>
        this.addValue(value, { render: false }),
      );
      this.render();
    }

    addValue(value, { render = true } = {}) {
      const text = String(value ?? "").trim();
      if (!text) return false;

      if (this.multi) {
        const exists = this.values.some((item) => item.toLowerCase() === text.toLowerCase());
        if (exists) return false;
        this.values.push(text);
      } else {
        this.values = [text];
      }

      if (render) this.render();
      return true;
    }

    removeValue(value) {
      const index = this.values.indexOf(value);
      if (index === -1) return;
      this.values.splice(index, 1);
      this.render();
    }

    // ----- Options ----- //

    setOptions(options) {
      this.options = (Array.isArray(options) ? options : [])
        .map((option) => ({
          value: String(option?.value ?? "").trim(),
          count: Number(option?.count) || 0,
        }))
        .filter((option) => option.value);
      this.render();
    }

    availableOptions() {
      const selected = new Set(this.values.map((value) => value.toLowerCase()));
      return this.options.filter((option) => !selected.has(option.value.toLowerCase()));
    }

    countFor(value) {
      const found = this.options.find(
        (option) => option.value.toLowerCase() === value.toLowerCase(),
      );
      return found ? found.count : 0;
    }

    // The count tells the user how many recipes already use the value.
    labelFor(value) {
      const count = this.countFor(value);
      return count ? `${value} (${count})` : value;
    }

    // The combo variant keeps the text input as the source of truth, so the
    // typed text is trimmed on read instead of on every keystroke.
    handleInput() {
      const text = this.input.value.trim();
      this.values = text ? [text] : [];
    }

    // ----- Rendering ----- //

    render() {
      if (this.combo) {
        this.input.value = this.values[0] ?? "";
      } else {
        this.renderChips();
      }
      this.renderSelect();
    }

    renderSelect() {
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = this.selectLabel();

      const options = [placeholder];
      if (this.combo) {
        // The combo input is typeable, so there is no "Add new" option and
        // the library is always offered in full.
        this.options.forEach((option) => {
          const element = document.createElement("option");
          element.value = option.value;
          element.textContent = this.labelFor(option.value);
          options.push(element);
        });
      } else {
        // "Add new" sits at the top so a value that is not in the library
        // yet is always one click away.
        const addNew = document.createElement("option");
        addNew.value = NEW_VALUE;
        addNew.textContent = "Add new…";

        options.push(addNew);
        this.availableOptions().forEach((option) => {
          const element = document.createElement("option");
          element.value = option.value;
          element.textContent = this.labelFor(option.value);
          options.push(element);
        });
      }

      this.select.replaceChildren(...options);
      this.select.value = "";
    }

    renderChips() {
      if (this.combo) return;

      const chips = this.values.map((value) => {
        const chip = document.createElement("span");
        chip.className = "recipe-editor__picker-chip";
        chip.dataset.value = value;

        const label = document.createElement("span");
        label.className = "recipe-editor__picker-chip-label";
        label.textContent = this.labelFor(value);

        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "recipe-editor__picker-chip-remove";
        remove.setAttribute("aria-label", `Remove ${value}`);
        applyXIcon(remove);
        remove.disabled = this.disabled;
        remove.addEventListener("click", () => this.removeValue(value));

        chip.append(label, remove);
        return chip;
      });

      this.valuesElement.replaceChildren(...chips);
    }

    // ----- Adding a value ----- //

    handleSelectChange() {
      const value = this.select.value;
      if (!value) return;

      if (value === NEW_VALUE) {
        this.startNewValue();
        return;
      }

      this.select.value = "";
      this.addValue(value);
    }

    startNewValue() {
      this.select.hidden = true;
      this.newInput.hidden = false;
      this.addButton.hidden = false;
      this.newInput.value = "";
      this.newInput.disabled = this.disabled;
      this.addButton.disabled = this.disabled;
      this.newInput.focus();
    }

    cancelNewValue() {
      this.newInput.hidden = true;
      this.addButton.hidden = true;
      this.newInput.value = "";
      this.select.hidden = false;
      this.select.value = "";
    }

    commitNewValue() {
      const value = this.newInput.value.trim();
      this.newInput.value = "";
      this.addValue(value);
      this.cancelNewValue();
    }

    handleNewInputKey(event) {
      if (event.key === "Enter") {
        event.preventDefault();
        this.commitNewValue();
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        this.cancelNewValue();
      }
    }

    // ----- Disabled state ----- //

    setDisabled(disabled) {
      this.disabled = Boolean(disabled);
      this.select.disabled = this.disabled;
      if (this.combo) {
        this.input.disabled = this.disabled;
      } else {
        this.newInput.disabled = this.disabled;
        this.addButton.disabled = this.disabled;
      }
      this.renderChips();
    }
  }

  function createPickers(root) {
    const pickers = new Map();

    root.querySelectorAll(".recipe-editor__picker").forEach((element) => {
      const picker = new MetadataPicker(element);
      pickers.set(picker.field, picker);
    });

    return {
      get: (field) => pickers.get(field) ?? null,
      values: (field) => pickers.get(field)?.getValues() ?? [],
      setValues: (field, values) => pickers.get(field)?.setValues(values),
      setOptions: (field, options) => pickers.get(field)?.setOptions(options),
      setDisabled: (disabled) => pickers.forEach((picker) => picker.setDisabled(disabled)),
      fields: () => [...pickers.keys()],
    };
  }

  window.RecipeMetadataPicker = { MetadataPicker, createPickers, FIELDS, NEW_VALUE };
})();
