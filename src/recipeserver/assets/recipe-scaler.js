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

  constructor() {
    this.scaleSelect = document.getElementById("recipe-scale-select");
    this.customInput = document.getElementById("recipe-scale-custom");
    this.quantities = document.querySelectorAll(".quantity");
    this.isReady = Boolean(this.scaleSelect && this.customInput);

    if (!this.isReady) {
      console.warn("RecipeScaler: scale controls not found");
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

      this.update();
    });

    this.customInput.addEventListener("focus", () => {
      this.customInput.select();
    });

    this.customInput.addEventListener("input", () => {
      this.update();
    });

    // ----- Initial render ----- //
    this.customInput.hidden = true;
    this.update();
  }

  async update() {
    if (!this.isReady) {
      return;
    }

    const mathJax = window.MathJax;

    if (!mathJax?.startup?.promise) {
      console.warn("RecipeScaler: MathJax hasn't loaded. Check script order.");
      return;
    }

    await mathJax.startup.promise;

    const scale =
      this.scaleSelect.value === "custom"
        ? parseFloat(this.customInput.value)
        : parseFloat(this.scaleSelect.value);

    if (!Number.isFinite(scale) || scale <= 0) {
      return;
    }

    // Clear MathJax's bookkeeping for the old rendered content.
    if (typeof mathJax.typesetClear === "function") {
      mathJax.typesetClear([...this.quantities]);
    }
    for (const element of this.quantities) {
      const quantity = parseFloat(element.dataset.quantity);
      const unit = element.dataset.unit ?? "";
      const quantityEnd = element.dataset.quantityEnd;

      if (!Number.isFinite(quantity)) {
        continue;
      }

      const scaled = this.roundQuantity(quantity * scale, unit);
      let formatted = this.formatQuantity(scaled, unit);

      if (quantityEnd !== undefined) {
        formatted = this.formatQuantityRange(scaled, quantityEnd, scale, unit, formatted);
      }

      element.innerHTML = formatted;
    }

    await this.typesetMath();
  }

  async typesetMath() {
    const mathJax = window.MathJax;

    if (typeof mathJax?.typesetPromise !== "function") {
      console.warn("RecipeScaler: MathJax typesetting is unavailable.");
      return;
    }

    await mathJax.startup.promise;
    await mathJax.typesetPromise([...this.quantities]);
  }

  formatQuantityRange(scaledStart, quantityEndRaw, scale, unit, formattedStart) {
    const quantityEnd = parseFloat(quantityEndRaw);
    if (!Number.isFinite(quantityEnd)) {
      return formattedStart;
    }

    const scaledEnd = this.roundQuantity(quantityEnd * scale, unit);
    const formattedEnd = this.formatQuantity(scaledEnd, unit);
    const formattedUnit = this.formatUnit(unit, scaledStart);

    const separator = formattedUnit && this.requiresSpaceBeforeUnit(formattedUnit) ? " " : "";
    const unitSuffix = formattedUnit ? `${separator}${formattedUnit}` : "";
    const endWithoutUnit =
      unitSuffix && formattedEnd.endsWith(unitSuffix)
        ? formattedEnd.slice(0, -unitSuffix.length)
        : formattedEnd;

    const startMath = this.unwrapMathText(formattedStart.replace(unitSuffix, ""));
    const endMath = this.unwrapMathText(endWithoutUnit);
    return `$${startMath}\\text{ - }${endMath}$${unitSuffix}`;
  }

  unwrapMathText(formattedText) {
    const wrappedMath = /^\$(.*?)\$$/.exec(formattedText);
    return wrappedMath ? wrappedMath[1] : formattedText;
  }

  roundQuantity(value, unit) {
    const weightUnits = new Set(["g", "gram", "grams", "kg", "mg"]);
    if (weightUnits.has(unit)) {
      return Math.round(value);
    }

    // Fractional kitchen measures and count-like items keep their scaled value.
    return value;
  }
  requiresSpaceBeforeUnit(unit) {
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

  formatQuantity(value, unit) {
    const quantity = this.formatNumber(value);
    const formattedUnit = this.formatUnit(unit, value);

    if (!formattedUnit) {
      return `$${quantity}$`;
    }

    const separator = this.requiresSpaceBeforeUnit(formattedUnit) ? " " : "";

    return `$${quantity}$${separator}${formattedUnit}`;
  }
  formatNumber(value) {
    const whole = Math.floor(value);
    const decimal = value - whole;

    const fractions = [
      { value: 0, latex: "" },
      { value: 1 / 8, latex: "\\frac{1}{8}" },
      // { value: 1 / 6, latex: "\\frac{1}{6}" },
      { value: 1 / 4, latex: "\\frac{1}{4}" },
      { value: 1 / 3, latex: "\\frac{1}{3}" },
      { value: 3 / 8, latex: "\\frac{3}{8}" },
      { value: 1 / 2, latex: "\\frac{1}{2}" },
      { value: 5 / 8, latex: "\\frac{5}{8}" },
      { value: 2 / 3, latex: "\\frac{2}{3}" },
      { value: 3 / 4, latex: "\\frac{3}{4}" },
      // { value: 5 / 6, latex: "\\frac{5}{6}" },
      { value: 7 / 8, latex: "\\frac{7}{8}" },
      { value: 1, latex: "" },
    ];

    const nearest = fractions.reduce((best, current) =>
      Math.abs(current.value - decimal) < Math.abs(best.value - decimal) ? current : best,
    );

    // Rounding up to the next whole number.
    if (nearest.value === 1) {
      return `${whole + 1}`;
    }

    // Exact whole number.
    if (nearest.value === 0) {
      return `${whole}`;
    }

    // Fraction less than one.
    if (whole === 0) {
      return nearest.latex;
    }

    // Mixed number.
    return `${whole}\\,${nearest.latex}`;
  }

  formatUnit(unit, quantity) {
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
      return this.pluralizeMeasurement(unit, quantity);
    }

    return this.pluralize(unit, quantity);
  }

  pluralizeMeasurement(unit, quantity) {
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

  pluralize(unit, quantity) {
    const words = unit.trim().split(/\s+/);
    if (words.length === 0) {
      return unit;
    }

    const noun = words.pop();
    const singular = this.singularizeWord(noun);

    if (quantity === 1) {
      return [...words, singular].join(" ");
    }

    return [...words, this.pluralizeWord(singular)].join(" ");
  }

  singularize(unit) {
    const words = unit.trim().split(/\s+/);
    if (words.length === 0) {
      return unit;
    }

    const noun = words.pop();
    return [...words, this.singularizeWord(noun)].join(" ");
  }

  pluralizeWord(singular) {
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

  singularizeWord(noun) {
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
}

document.addEventListener("DOMContentLoaded", () => {
  new RecipeScaler();
});
