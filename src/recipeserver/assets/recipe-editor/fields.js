/**
 * Recipe editor field scaffolding.
 *
 * The metadata/source/rating fields in the editor dialog all share one
 * structure: a label, a "* MIXED" chip (bulk mode), a field control, and a
 * hidden per-field "Save" button that writes the field to every recipe in a
 * bulk selection. The fields are declared as data below and built by
 * buildFieldGroups() so the chip, wrapper, and button are defined exactly
 * once. Adding a field is one descriptor.
 */

(function () {
  const MIXED_TEXT = "* MIXED";

  // ----- Field descriptors ----- //
  // Control kinds: "picker" (metadata dropdown), "input" (plain input),
  // "select" (plain select), "checkbox" (checkbox + trailing label text).
  // saveName defaults to the lower-cased label and feeds the bulk-save
  // button's aria-label; fields sharing one metadata key (the sources) pass
  // their own saveName. rating.score carries no MIXED chip or Save button.
  const DETAILS_FIELDS = [
    { label: "Contributor", field: "contributor", picker: true },
    {
      label: "Contribution Date",
      field: "createdOn",
      saveName: "contribution date",
      input: { name: "createdOn", type: "date" },
    },
    { label: "Meals", field: "meals", picker: true },
    { label: "Categories", field: "categories", picker: true },
    { label: "Cuisine", field: "cuisine", picker: true },
    { label: "Status", field: "status", picker: true },
    { label: "Tags", field: "tags", picker: true },
    {
      label: "Makes",
      field: "makes",
      numeric: true,
      input: { name: "makes", type: "number", step: "1", placeholder: "0" },
    },
    {
      label: "Difficulty",
      field: "difficulty",
      numeric: true,
      input: { name: "difficulty", type: "number", step: "any", placeholder: "5" },
    },
    { label: "Archived", field: "archived", checkbox: true },
  ];

  const SOURCE_OPTIONS = ["Website", "AI", "Book", "Other"];
  const SOURCES_FIELDS = [
    {
      label: "Source Author",
      field: "source",
      saveName: "source",
      input: { name: "source.author", type: "text", placeholder: "First Last" },
    },
    {
      label: "Source Title",
      field: "source",
      saveName: "source",
      input: {
        name: "source.title",
        type: "text",
        placeholder: "Book Title, Website Name, AI Model, etc.",
      },
    },
    {
      label: "Source Format",
      field: "source",
      saveName: "source",
      select: { name: "source.format", options: SOURCE_OPTIONS },
    },
    {
      label: "Source URL",
      field: "source",
      saveName: "source",
      input: { name: "source.url", type: "url", placeholder: "example.com/recipe-page" },
    },
  ];

  const RATINGS_FIELDS = [
    {
      label: "Rating name",
      field: "rating",
      saveName: "rating",
      input: { name: "rating.name", type: "text", placeholder: "Andy Ford" },
    },
    {
      label: "Rating score (0-10)",
      field: null,
      noMixedSave: true,
      input: {
        name: "rating.score",
        type: "number",
        step: "any",
        min: "0",
        max: "10",
        placeholder: "8",
      },
    },
  ];

  const FIELD_GROUPS = {
    details: DETAILS_FIELDS,
    sources: SOURCES_FIELDS,
    ratings: RATINGS_FIELDS,
  };

  // ----- Builder ----- //

  function mixedBadge() {
    const mixed = document.createElement("span");
    mixed.className = "recipe-editor__mixed";
    mixed.hidden = true;
    mixed.textContent = MIXED_TEXT;
    return mixed;
  }

  function fieldControl() {
    const control = document.createElement("span");
    control.className = "recipe-editor__field-control";
    return control;
  }

  function bulkSaveButton(field, saveName) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "recipe-editor__bulk-field-save";
    button.dataset.field = field;
    button.setAttribute("aria-label", `Save ${saveName} to all selected recipes`);
    button.hidden = true;
    button.textContent = "Save";
    return button;
  }

  function buildControl(descriptor) {
    if (descriptor.picker) {
      const picker = document.createElement("span");
      picker.className = "recipe-editor__picker";
      picker.dataset.field = descriptor.field;
      return picker;
    }
    if (descriptor.select) {
      const select = document.createElement("select");
      select.setAttribute("name", descriptor.select.name);
      const empty = document.createElement("option");
      empty.value = "";
      empty.textContent = "Select format";
      select.append(empty);
      for (const option of descriptor.select.options) {
        const element = document.createElement("option");
        element.value = option;
        element.textContent = option;
        select.append(element);
      }
      return select;
    }
    const input = document.createElement("input");
    for (const [key, value] of Object.entries(descriptor.input)) {
      input.setAttribute(key, value);
    }
    return input;
  }

  function saveName(descriptor) {
    return descriptor.saveName || descriptor.label.toLowerCase();
  }

  function buildField(descriptor) {
    const label = document.createElement("label");

    if (descriptor.checkbox) {
      // The checkbox layout keeps the input, its text, the MIXED chip, and
      // the Save button inside one control wrapper.
      label.className = "recipe-editor__checkbox";
      const control = fieldControl();
      const input = document.createElement("input");
      input.setAttribute("name", descriptor.field);
      input.setAttribute("type", "checkbox");
      const text = document.createElement("span");
      text.textContent = descriptor.label;
      control.append(
        input,
        text,
        mixedBadge(),
        bulkSaveButton(descriptor.field, saveName(descriptor)),
      );
      label.append(control);
      return label;
    }

    label.textContent = descriptor.label;
    if (!descriptor.noMixedSave) {
      label.append(mixedBadge());
    }

    const control = fieldControl();
    control.append(buildControl(descriptor));
    if (!descriptor.noMixedSave) {
      control.append(bulkSaveButton(descriptor.field, saveName(descriptor)));
    }
    label.append(control);
    return label;
  }

  function buildFieldGroups(root) {
    for (const [group, descriptors] of Object.entries(FIELD_GROUPS)) {
      const container = root.querySelector(`[data-field-group="${group}"]`);
      if (!container) continue;

      let numericWrapper = null;
      for (const descriptor of descriptors) {
        if (descriptor.numeric) {
          if (!numericWrapper) {
            numericWrapper = document.createElement("div");
            numericWrapper.className = "recipe-editor__numeric";
            container.append(numericWrapper);
          }
          numericWrapper.append(buildField(descriptor));
          continue;
        }
        numericWrapper = null;
        container.append(buildField(descriptor));
      }
    }
  }

  window.RecipeEditorFields = { buildFieldGroups };
})();
