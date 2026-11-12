class RecipeScaler {
  // ----- Noun forms ----- //
  // Single source of truth for irregular noun singular/plural pairs.
  static IRREGULAR_NOUN_FORMS = [
    ["loaf", "loaves"],
    ["leaf", "leaves"],
    ["knife", "knives"],
    ["half", "halves"],
    ["potato", "potatoes"],
    ["tomato", "tomatoes"],
    ["person", "people"],
    ["child", "children"],
    ["mouse", "mice"],
    ["man", "men"],
    ["woman", "women"],
  ];

  static IRREGULAR_SINGULAR_TO_PLURAL = Object.fromEntries(RecipeScaler.IRREGULAR_NOUN_FORMS);
  static IRREGULAR_PLURAL_TO_SINGULAR = Object.fromEntries(
    RecipeScaler.IRREGULAR_NOUN_FORMS.map(([singular, plural]) => [plural, singular]),
  );

  // ----- Fraction table ----- //
  // Each fraction carries a LaTeX form for KaTeX and a plain text form
  // for callers that need to read a quantity back (the shopping list
  // checklist, for example).
  static FRACTIONS = [
    { value: 0, latex: "", text: "" },
    { value: 1 / 8, latex: "\\frac{1}{8}", text: "1/8" },
    // { value: 1 / 6, latex: "\\frac{1}{6}", text: "1/6" },
    { value: 1 / 4, latex: "\\frac{1}{4}", text: "1/4" },
    { value: 1 / 3, latex: "\\frac{1}{3}", text: "1/3" },
    { value: 3 / 8, latex: "\\frac{3}{8}", text: "3/8" },
    { value: 1 / 2, latex: "\\frac{1}{2}", text: "1/2" },
    { value: 5 / 8, latex: "\\frac{5}{8}", text: "5/8" },
    { value: 2 / 3, latex: "\\frac{2}{3}", text: "2/3" },
    { value: 3 / 4, latex: "\\frac{3}{4}", text: "3/4" },
    // { value: 5 / 6, latex: "\\frac{5}{6}", text: "5/6" },
    { value: 7 / 8, latex: "\\frac{7}{8}", text: "7/8" },
    { value: 1, latex: "", text: "" },
  ];

  // ----- Amount formatting ----- //
  // The formatters below are static so other features can reuse them. The
  // shopping list adds the amounts of several recipes together and needs
  // the same formatting the recipe pages use.

  static roundQuantity(value, unit) {
    const weightUnits = new Set(["g", "gram", "grams", "kg", "mg"]);
    if (weightUnits.has(unit)) {
      return Math.round(value);
    }

    // Fractional kitchen measures and count-like items keep their scaled value.
    return value;
  }

  static requiresSpaceBeforeUnit(unit) {
    const attachedUnits = [
      "lb",
      "lbs",
      "oz",
      "g",
      "gram",
      "grams",
      "kg",
      "mg",
      "mcg",
      "μg",
      "mL",
      "L",
      "ml",
      "cl",
      "dl",
    ];

    return !attachedUnits.includes(unit);
  }

  static formatQuantity(value, unit) {
    const quantity = RecipeScaler.formatNumber(value);
    const formattedUnit = RecipeScaler.formatUnit(unit, value);

    if (!formattedUnit) {
      return `$${quantity}$`;
    }

    const separator = RecipeScaler.requiresSpaceBeforeUnit(formattedUnit) ? " " : "";

    return `$${quantity}$${separator}${formattedUnit}`;
  }

  static formatQuantityText(value, unit) {
    const quantity = RecipeScaler.formatNumberText(value);
    const formattedUnit = RecipeScaler.formatUnit(unit, value);

    if (!formattedUnit) {
      return quantity;
    }

    const separator = RecipeScaler.requiresSpaceBeforeUnit(formattedUnit) ? " " : "";

    return `${quantity}${separator}${formattedUnit}`;
  }

  // Format a range whose ends are already scaled.
  static formatScaledRange(scaledStart, scaledEnd, unit) {
    const formattedStart = RecipeScaler.formatQuantity(scaledStart, unit);
    const formattedEnd = RecipeScaler.formatQuantity(scaledEnd, unit);
    const formattedUnit = RecipeScaler.formatUnit(unit, scaledStart);

    const separator =
      formattedUnit && RecipeScaler.requiresSpaceBeforeUnit(formattedUnit) ? " " : "";
    const unitSuffix = formattedUnit ? `${separator}${formattedUnit}` : "";
    const endWithoutUnit =
      unitSuffix && formattedEnd.endsWith(unitSuffix)
        ? formattedEnd.slice(0, -unitSuffix.length)
        : formattedEnd;

    const startMath = RecipeScaler.unwrapMathText(formattedStart.replace(unitSuffix, ""));
    const endMath = RecipeScaler.unwrapMathText(endWithoutUnit);
    return `$${startMath}\\text{ - }${endMath}$${unitSuffix}`;
  }

  static formatScaledRangeText(scaledStart, scaledEnd, unit) {
    const formattedUnit = RecipeScaler.formatUnit(unit, scaledStart);

    const separator =
      formattedUnit && RecipeScaler.requiresSpaceBeforeUnit(formattedUnit) ? " " : "";
    const unitSuffix = formattedUnit ? `${separator}${formattedUnit}` : "";

    const startText = RecipeScaler.formatNumberText(scaledStart);
    const endText = RecipeScaler.formatNumberText(scaledEnd);
    return `${startText} - ${endText}${unitSuffix}`;
  }

  static formatQuantityRange(scaledStart, quantityEndRaw, scale, unit) {
    const quantityEnd = parseFloat(quantityEndRaw);
    if (!Number.isFinite(quantityEnd)) {
      return RecipeScaler.formatQuantity(scaledStart, unit);
    }

    const scaledEnd = RecipeScaler.roundQuantity(quantityEnd * scale, unit);
    return RecipeScaler.formatScaledRange(scaledStart, scaledEnd, unit);
  }

  static formatQuantityRangeText(scaledStart, quantityEndRaw, scale, unit) {
    const quantityEnd = parseFloat(quantityEndRaw);
    if (!Number.isFinite(quantityEnd)) {
      return RecipeScaler.formatQuantityText(scaledStart, unit);
    }

    const scaledEnd = RecipeScaler.roundQuantity(quantityEnd * scale, unit);
    return RecipeScaler.formatScaledRangeText(scaledStart, scaledEnd, unit);
  }

  static unwrapMathText(formattedText) {
    const wrappedMath = /^\$(.*?)\$$/.exec(formattedText);
    return wrappedMath ? wrappedMath[1] : formattedText;
  }

  static formatNumberParts(value) {
    const whole = Math.floor(value);
    const decimal = value - whole;

    const nearest = RecipeScaler.FRACTIONS.reduce((best, current) =>
      Math.abs(current.value - decimal) < Math.abs(best.value - decimal) ? current : best,
    );

    // Rounding up to the next whole number.
    if (nearest.value === 1) {
      return { whole: whole + 1, fraction: null };
    }

    // Exact whole number.
    if (nearest.value === 0) {
      return { whole, fraction: null };
    }

    return { whole, fraction: nearest };
  }

  static formatNumber(value) {
    const { whole, fraction } = RecipeScaler.formatNumberParts(value);

    if (!fraction) {
      return `${whole}`;
    }

    // Fraction less than one.
    if (whole === 0) {
      return fraction.latex;
    }

    // Mixed number.
    return `${whole}\\,${fraction.latex}`;
  }

  static formatNumberText(value) {
    const { whole, fraction } = RecipeScaler.formatNumberParts(value);

    if (!fraction) {
      return `${whole}`;
    }

    // Fraction less than one.
    if (whole === 0) {
      return fraction.text;
    }

    // Mixed number.
    return `${whole} ${fraction.text}`;
  }

  static formatUnit(unit, quantity) {
    if (!unit) {
      return "";
    }

    const measurementUnits = [
      "tsp",
      "tbsp",
      "cup",
      "cups",
      "oz",
      "lb",
      "lbs",
      "g",
      "gram",
      "grams",
      "kg",
      "mg",
      "mL",
      "L",
    ];

    if (measurementUnits.includes(unit)) {
      return RecipeScaler.pluralizeMeasurement(unit, quantity);
    }

    return RecipeScaler.pluralize(unit, quantity);
  }

  static pluralizeMeasurement(unit, quantity) {
    // Normalize measurement units to singular first.
    const singular =
      {
        cups: "cup",
        cup: "cup",
        tsp: "tsp",
        tbsp: "tbsp",
        oz: "oz",
        lb: "lb",
        lbs: "lb",
        g: "g",
        gram: "g",
        grams: "g",
        kg: "kg",
        mg: "mg",
        mL: "mL",
        L: "L",
      }[unit] ?? unit;

    if (quantity <= 1) {
      return singular;
    }

    const plurals = {
      cup: "cups",
      gram: "grams",
    };

    return plurals[singular] ?? singular;
  }

  static pluralize(unit, quantity) {
    const words = unit.trim().split(/\s+/);
    if (words.length === 0) {
      return unit;
    }

    const noun = words.pop();
    const singular = RecipeScaler.singularizeWord(noun);

    if (quantity === 1) {
      return [...words, singular].join(" ");
    }

    return [...words, RecipeScaler.pluralizeWord(singular)].join(" ");
  }

  static singularize(unit) {
    const words = unit.trim().split(/\s+/);
    if (words.length === 0) {
      return unit;
    }

    const noun = words.pop();
    return [...words, RecipeScaler.singularizeWord(noun)].join(" ");
  }

  static pluralizeWord(singular) {
    const irregularPlural = RecipeScaler.IRREGULAR_SINGULAR_TO_PLURAL[singular];
    if (irregularPlural) {
      return irregularPlural;
    }
    if (singular.endsWith("y") && !/[aeiou]y$/.test(singular)) {
      return `${singular.slice(0, -1)}ies`;
    }
    if (/(?:s|sh|ch|x|z)$/.test(singular)) {
      return `${singular}es`;
    }
    return `${singular}s`;
  }

  static singularizeWord(noun) {
    const irregularSingular = RecipeScaler.IRREGULAR_PLURAL_TO_SINGULAR[noun];
    if (irregularSingular) {
      return irregularSingular;
    }
    if (noun.endsWith("ies")) {
      return `${noun.slice(0, -3)}y`;
    }
    if (/(?:ses|shes|ches|xes|zes)$/.test(noun)) {
      return noun.slice(0, -2);
    }
    if (noun.endsWith("s")) {
      return noun.slice(0, -1);
    }
    return noun;
  }

  // Render a formatted amount into an element with KaTeX.
  static renderQuantity(element, formatted) {
    const match = /^\$(.*)\$(.*)$/s.exec(formatted);
    const latex = match ? match[1] : formatted;
    const suffix = match ? match[2] : "";

    if (typeof window.katex?.render !== "function") {
      console.warn("RecipeScaler: KaTeX hasn't loaded. Check script order.");
      element.textContent = `${latex}${suffix}`;
      element.classList.add("is-rendered");
      return;
    }

    katex.render(latex, element, { throwOnError: false });
    element.classList.add("is-rendered");

    if (suffix) {
      element.append(document.createTextNode(suffix));
    }
  }

  /**
   * Scale the quantities inside `root`.
   *
   * @param {ParentNode} root Scope that holds the scaler controls and the
   *   quantities they scale. The recipe page passes the document because
   *   its scaler sits in the header while the quantities sit in the body;
   *   the shopping list passes a single recipe row so every recipe can be
   *   scaled on its own.
   * @param {{onUpdate?: () => void}} [options] `onUpdate` runs after every
   *   recalculation so callers can re-render derived content.
   */
  constructor(root = document, options = {}) {
    this.root = root;
    this.onUpdate = options.onUpdate ?? null;
    this.scalerElement = root.querySelector(".recipe-scaler");
    this.scaleSelect = this.scalerElement?.querySelector(".recipe-scale-select") ?? null;
    this.customInput = this.scalerElement?.querySelector(".recipe-scale-custom") ?? null;
    this.quantities = root.querySelectorAll(".quantity");
    this.isReady = Boolean(this.scaleSelect && this.customInput);

    if (!this.isReady) {
      console.warn("RecipeScaler: scale controls not found");
      this.revealScaler();
      return;
    }

    // ----- Wire controls ----- //
    this.scaleSelect.addEventListener("change", () => {
      const isCustom = this.scaleSelect.value === "custom";

      this.scaleSelect.hidden = isCustom;
      this.customInput.hidden = !isCustom;

      if (isCustom) {
        this.customInput.focus();
        this.customInput.select();
      }

      this.autoSizeControls();
      this.update();
    });

    this.customInput.addEventListener("focus", () => {
      this.customInput.select();
    });

    this.customInput.addEventListener("input", () => {
      this.autoSizeControls();
      this.update();
    });

    window.addEventListener("resize", () => {
      this.autoSizeControls();
    });

    // ----- Initial render ----- //
    this.customInput.hidden = true;
    this.autoSizeControls();
    this.update();
    this.revealScaler();

    // Never keep the scaler hidden if something above threw before
    // the reveal (e.g. KaTeX failed to load).
    this.revealTimer = window.setTimeout(() => {
      this.revealScaler();
    }, 3000);
  }

  revealScaler() {
    if (!this.scalerElement) {
      return;
    }

    this.scalerElement.classList.add("is-ready");
    if (this.revealTimer) {
      window.clearTimeout(this.revealTimer);
      this.revealTimer = null;
    }
  }

  // ----- Dynamic control sizing ----- //
  // `field-sizing: content` handles this in modern browsers; this
  // fallback sizes the controls to their text so a 1-digit value
  // does not sit in a 3.5ch gap and a 3-4 digit value is not clipped.
  autoSizeControls() {
    if (!this.isReady) {
      return;
    }

    const supportsFieldSizing = typeof CSS !== "undefined" && CSS.supports("field-sizing: content");

    if (supportsFieldSizing) {
      this.scaleSelect.style.width = "";
      this.customInput.style.width = "";
      return;
    }

    this.scaleSelect.style.width = `${this.measureTextWidth(this.scaleSelect, this.selectedOptionText(this.scaleSelect))}px`;
    this.customInput.style.width = `${this.measureTextWidth(this.customInput, this.customInput.value || "1")}px`;
  }

  selectedOptionText(select) {
    const option = select.options[select.selectedIndex];
    return option ? option.textContent : select.value;
  }

  measureTextWidth(control, text) {
    try {
      const style = getComputedStyle(control);
      const font = style.font || `${style.fontSize} ${style.fontFamily}`;
      const canvas = this.measureCanvas ?? (this.measureCanvas = document.createElement("canvas"));
      const context = canvas.getContext("2d");
      if (context) {
        context.font = font;
        const padding = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
        return context.measureText(text).width + padding;
      }
    } catch {
      // Fall through to the character-count fallback below.
    }

    return Math.max(text.length, 1);
  }

  update() {
    if (!this.isReady) {
      return;
    }

    const scale =
      this.scaleSelect.value === "custom"
        ? parseFloat(this.customInput.value)
        : parseFloat(this.scaleSelect.value);

    if (!Number.isFinite(scale) || scale <= 0) {
      return;
    }

    for (const element of this.quantities) {
      const quantity = parseFloat(element.dataset.quantity);
      const unit = element.dataset.unit ?? "";
      const quantityEnd = element.dataset.quantityEnd;

      if (!Number.isFinite(quantity)) {
        continue;
      }

      const scaled = RecipeScaler.roundQuantity(quantity * scale, unit);
      let formatted = RecipeScaler.formatQuantity(scaled, unit);
      let text = RecipeScaler.formatQuantityText(scaled, unit);
      let scaledEnd = null;

      if (quantityEnd !== undefined) {
        formatted = RecipeScaler.formatQuantityRange(scaled, quantityEnd, scale, unit);
        text = RecipeScaler.formatQuantityRangeText(scaled, quantityEnd, scale, unit);

        const endValue = parseFloat(quantityEnd);
        if (Number.isFinite(endValue)) {
          scaledEnd = RecipeScaler.roundQuantity(endValue * scale, unit);
        }
      }

      // Keep the scaled amount available as plain text and as a number so
      // callers that cannot read the rendered KaTeX output (the shopping
      // list checklist, for example) can still work with it.
      element.dataset.scaledText = text;
      element.dataset.scaledQuantity = String(scaled);
      if (scaledEnd !== null) {
        element.dataset.scaledQuantityEnd = String(scaledEnd);
      }

      RecipeScaler.renderQuantity(element, formatted);
    }

    if (this.onUpdate) {
      this.onUpdate();
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  // Only the recipe page has a scaler of its own. Pages that embed the
  // scaler markup (the shopping list) create their own instances.
  if (!document.querySelector(".recipe-scaler")) return;
  new RecipeScaler();
});
