/**
 * Recipe editor field scaffolding.
 *
 * The metadata/source/rating fields in the editor dialog all share one
 * structure: a label, a "Modified" chip (bulk mode), and a field control.
 * The fields are declared as data below and built by buildFieldGroups() so
 * the chip, wrapper, and control are defined exactly once. Adding a field is
 * one descriptor.
 */

(function () {
  const MODIFIED_TEXT = "Modified";

  // ----- Field descriptors ----- //
  // Control kinds: "picker" (metadata dropdown), "input" (plain input),
  // "select" (plain select), "checkbox" (checkbox + trailing label text).
  // A picker may carry its own pickerField for the widget's data-field (the
  // source pickers key on "source.author" / "source.title" while the bulk
  // edit applies the shared "source" key). rating.score carries no Modified
  // chip; the rating is tracked as a whole by the editor.
  const DETAILS_FIELDS = [
    { label: "Contributor", field: "contributor", picker: true },
    {
      label: "Contribution Date",
      field: "createdOn",
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
      field: "source.author",
      picker: true,
      pickerField: "source.author",
    },
    {
      label: "Source Title",
      field: "source.title",
      picker: true,
      pickerField: "source.title",
    },
    {
      label: "Source Format",
      field: "source.format",
      select: { name: "source.format", options: SOURCE_OPTIONS },
    },
    {
      label: "Source URL",
      field: "source.url",
      input: { name: "source.url", type: "url", placeholder: "example.com/recipe-page" },
    },
  ];

  const RATINGS_FIELDS = [
    {
      label: "Rating name",
      field: "rating.name",
      input: { name: "rating.name", type: "text", placeholder: "Andy Ford" },
    },
    {
      label: "Rating score (0-10)",
      field: null,
      noModifiedBadge: true,
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

  function modifiedBadge() {
    const modified = document.createElement("span");
    modified.className = "recipe-editor__modified";
    modified.hidden = true;
    modified.textContent = MODIFIED_TEXT;
    return modified;
  }

  function fieldControl() {
    const control = document.createElement("span");
    control.className = "recipe-editor__field-control";
    return control;
  }

  function buildControl(descriptor) {
    if (descriptor.picker) {
      const picker = document.createElement("span");
      picker.className = "recipe-editor__picker";
      picker.dataset.field = descriptor.pickerField ?? descriptor.field;
      return picker;
    }
    if (descriptor.select) {
      const select = document.createElement("select");
      select.setAttribute("name", descriptor.select.name);
      select.setAttribute("class", "field-input");
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
    input.setAttribute("class", "field-input");
    return input;
  }

  function buildField(descriptor) {
    const label = document.createElement("label");

    if (descriptor.checkbox) {
      // The checkbox layout keeps the input, its text, and the Modified chip
      // inside one control wrapper.
      label.className = "recipe-editor__checkbox";
      const control = fieldControl();
      const input = document.createElement("input");
      input.setAttribute("name", descriptor.field);
      input.setAttribute("type", "checkbox");
      const text = document.createElement("span");
      text.textContent = descriptor.label;
      control.append(input, text, modifiedBadge());
      label.append(control);
      return label;
    }

    const heading = document.createElement("span");
    heading.className = "recipe-editor__field-heading";
    heading.textContent = descriptor.label;

    if (!descriptor.noModifiedBadge) {
      heading.append(modifiedBadge());
    }
    label.append(heading);

    const control = fieldControl();
    control.append(buildControl(descriptor));
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
