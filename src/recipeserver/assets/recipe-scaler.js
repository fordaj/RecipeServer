class RecipeScaler {
  constructor() {
    this.scaleSelect = document.getElementById("recipe-scale-select");
    this.customInput = document.getElementById("recipe-scale-custom");
    this.quantities = document.querySelectorAll(".quantity");

    if (!this.scaleSelect || !this.customInput) {
      console.warn("RecipeScaler: scale controls not found");
      return;
    }

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

    // Initial render
    this.customInput.hidden = true;
    this.update(false);
  }

  async update() {
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
        const end = parseFloat(quantityEnd);

        if (Number.isFinite(end)) {
          const scaledEnd = this.roundQuantity(end * scale, unit);

          // Format the endpoint as a quantity, then remove its repeated unit.
          const formattedEnd = this.formatQuantity(scaledEnd, unit);
          const formattedUnit = this.formatUnit(unit, scaled);

          const separator = formattedUnit && this.requiresSpaceBeforeUnit(formattedUnit) ? " " : "";
          const unitSuffix = formattedUnit ? `${separator}${formattedUnit}` : "";

          const endText =
            unitSuffix && formattedEnd.endsWith(unitSuffix)
              ? formattedEnd.slice(0, -unitSuffix.length)
              : formattedEnd;

          const startText = formatted.replace(unitSuffix, "").replace(/^\$(.*?)\$$/, "$1");
          formatted = `$${startText}\\text{ - }${endText.replace(/^\$(.*?)\$$/, "$1")}$${unitSuffix ? separator + formattedUnit : ""}`;
        }
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

  roundQuantity(value, unit) {
    // Measurements that commonly use fractional amounts.
    if (["tsp", "tbsp", "cup"].includes(unit)) {
      return value;
    }

    // Weight measurements.
    if (["g", "gram", "grams", "kg", "mg"].includes(unit)) {
      return Math.round(value);
    }

    // Eggs, sticks of butter, etc
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
    const singular = this.singularize(noun);

    if (quantity === 1) {
      return [...words, singular].join(" ");
    }

    const irregular = {
      loaf: "loaves",
      leaf: "leaves",
      knife: "knives",
      half: "halves",
      potato: "potatoes",
      tomato: "tomatoes",
      person: "people",
      child: "children",
      mouse: "mice",
      man: "men",
      woman: "women",
    };

    let plural;

    if (irregular[singular]) {
      plural = irregular[singular];
    } else if (singular.endsWith("y") && !/[aeiou]y$/.test(singular)) {
      plural = singular.slice(0, -1) + "ies";
    } else if (
      singular.endsWith("s") ||
      singular.endsWith("sh") ||
      singular.endsWith("ch") ||
      singular.endsWith("x") ||
      singular.endsWith("z")
    ) {
      plural = singular + "es";
    } else {
      plural = singular + "s";
    }

    return [...words, plural].join(" ");
  }

  singularize(unit) {
    const words = unit.trim().split(/\s+/);

    if (words.length === 0) {
      return unit;
    }

    const noun = words.pop();

    const irregular = {
      loaves: "loaf",
      leaves: "leaf",
      knives: "knife",
      halves: "half",
      potatoes: "potato",
      tomatoes: "tomato",
      people: "person",
      children: "child",
      mice: "mouse",
      men: "man",
      women: "woman",
    };

    let singular;

    if (irregular[noun]) {
      singular = irregular[noun];
    } else if (noun.endsWith("ies")) {
      singular = noun.slice(0, -3) + "y";
    } else if (
      noun.endsWith("ses") ||
      noun.endsWith("shes") ||
      noun.endsWith("ches") ||
      noun.endsWith("xes") ||
      noun.endsWith("zes")
    ) {
      singular = noun.slice(0, -2);
    } else if (noun.endsWith("s")) {
      singular = noun.slice(0, -1);
    } else {
      singular = noun;
    }

    return [...words, singular].join(" ");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  new RecipeScaler();
});
