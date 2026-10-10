class RecipeScaler {
  constructor() {
    this.scaleInput = document.getElementById("recipe-scale");
    this.quantities = document.querySelectorAll(".quantity");

    if (!this.scaleInput) {
      console.warn("RecipeScaler: #recipe-scale not found");
      return;
    }

    this.scaleInput.addEventListener("input", () => {
      this.update();
    });

    // Initial render
    this.update(false);
  }

  async update(retypeset = true) {
    const scale = parseFloat(this.scaleInput.value);

    if (!Number.isFinite(scale) || scale <= 0) {
      return;
    }

    for (const element of this.quantities) {
      const quantity = parseFloat(element.dataset.quantity);
      const unit = element.dataset.unit ?? "";

      if (!Number.isFinite(quantity)) {
        continue;
      }

      const scaled = quantity * scale;
      const rounded = this.roundQuantity(scaled, unit);

      element.innerHTML = this.formatQuantity(rounded, unit);
    }

    if (retypeset) {
      await this.typesetMath();
    }
  }

  async typesetMath() {
    if (!window.MathJax?.startup?.promise) {
      console.warn("MathJax is not initialized yet");
      return;
    }

    await MathJax.startup.promise;

    if (typeof MathJax.typesetPromise !== "function") {
      console.warn("MathJax.typesetPromise is not available");
      return;
    }

    await MathJax.typesetPromise(this.quantities);
  }

  roundQuantity(value, unit) {
    // Measurements that commonly use fractional amounts.
    if (["tsp", "tbsp", "cup"].includes(unit)) {
      return Math.round(value * 8) / 8;
    }

    // Weight measurements.
    if (["g", "gram", "grams", "kg", "mg"].includes(unit)) {
      return Math.round(value);
    }

    // Eggs, sticks of butter, etc
    return Math.round(value * 8) / 8;
  }

  formatQuantity(value, unit) {
    const quantity = this.formatNumber(value);
    const formattedUnit = this.formatUnit(unit, value);

    if (!formattedUnit) {
      return `$${quantity}$`;
    }

    // MathJax handles the number; normal HTML handles the ingredient text.
    return `$${quantity}$ ${formattedUnit}`;
  }

  formatNumber(value) {
    const whole = Math.floor(value);
    const fraction = Math.round((value - whole) * 8);

    const fractions = {
      1: "\\frac{1}{8}",
      2: "\\frac{1}{4}",
      3: "\\frac{3}{8}",
      4: "\\frac{1}{2}",
      5: "\\frac{5}{8}",
      6: "\\frac{3}{4}",
      7: "\\frac{7}{8}",
    };

    // Exact whole number.
    if (fraction === 0) {
      return `${whole}`;
    }

    // Fraction less than one.
    if (whole === 0) {
      return fractions[fraction];
    }

    // Mixed number.
    return `${whole}\\,${fractions[fraction]}`;
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
      "g",
      "gram",
      "grams",
      "kg",
      "mg",
      "ml",
      "l",
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
        g: "g",
        gram: "gram",
        grams: "gram",
        kg: "kg",
        mg: "mg",
        ml: "ml",
        l: "l",
      }[unit] ?? unit;

    if (quantity === 1) {
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
