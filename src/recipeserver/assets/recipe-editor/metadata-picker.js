(() => {
  // A dropdown backed metadata field. The dropdown offers the values that are
  // already used in the recipe library; "Add new" swaps the dropdown for a
  // text field so a value that is not in the library yet can still be typed
  // in. Multi-value fields collect several values, single-value fields keep
  // exactly one.

  const NEW_VALUE = "__new__";

  const FIELDS = {
    meals: { label: "meal", mode: "multi" },
    categories: { label: "category", mode: "multi" },
    cuisine: { label: "cuisine", mode: "multi" },
    tags: { label: "tag", mode: "multi" },
    status: { label: "status", mode: "single" },
    contributor: { label: "contributor", mode: "single" },
  };

  function fieldConfig(field) {
    return FIELDS[field] ?? { label: field, mode: "single" };
  }

  class MetadataPicker {
    constructor(element) {
      this.element = element;
      this.field = element.dataset.field;
      this.config = fieldConfig(this.field);
      this.label = this.config.label;
      this.multi = this.config.mode === "multi";
      this.options = [];
      this.values = [];
      this.disabled = false;

      this.controls = document.createElement("span");
      this.controls.className = "recipe-editor__picker-controls";

      this.select = document.createElement("select");
      this.select.className = "recipe-editor__picker-select field-input";
      this.select.setAttribute("aria-label", this.selectLabel());

      this.newInput = document.createElement("input");
      this.newInput.className = "recipe-editor__picker-new field-input";
      this.newInput.type = "text";
      this.newInput.placeholder = `New ${this.label}`;
      this.newInput.setAttribute("aria-label", `New ${this.label}`);
      this.newInput.hidden = true;

      this.addButton = document.createElement("button");
      this.addButton.type = "button";
      this.addButton.className = "recipe-editor__picker-add";
      this.addButton.textContent = "Add";
      this.addButton.hidden = true;

      this.valuesElement = document.createElement("span");
      this.valuesElement.className = "recipe-editor__picker-values";

      this.controls.append(this.select, this.newInput, this.addButton);
      this.element.append(this.controls, this.valuesElement);

      this.select.addEventListener("change", () => this.handleSelectChange());
      this.addButton.addEventListener("click", () => this.commitNewValue());
      this.newInput.addEventListener("keydown", (event) => this.handleNewInputKey(event));

      this.render();
    }

    selectLabel() {
      return this.multi ? `Add ${this.label}` : `Select ${this.label}`;
    }

    // ----- Values ----- //

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

    // ----- Rendering ----- //

    render() {
      this.renderChips();
      this.renderSelect();
    }

    renderSelect() {
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = this.selectLabel();

      // "Add new" sits at the top so a value that is not in the library yet
      // is always one click away.
      const addNew = document.createElement("option");
      addNew.value = NEW_VALUE;
      addNew.textContent = "Add new…";

      const options = [placeholder, addNew];
      this.availableOptions().forEach((option) => {
        const element = document.createElement("option");
        element.value = option.value;
        element.textContent = this.labelFor(option.value);
        options.push(element);
      });

      this.select.replaceChildren(...options);
      this.select.value = "";
    }

    renderChips() {
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
        remove.textContent = "×";
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
      this.newInput.disabled = this.disabled;
      this.addButton.disabled = this.disabled;
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
