"use strict";

// Shared label rules, with an injectable `now` for cross-language comparison.

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const DATE_LABELS_JS = path.join(__dirname, "..", "..", "src", "recipeserver", "assets", "date-labels.js");

global.window = {};
vm.runInThisContext(fs.readFileSync(DATE_LABELS_JS, "utf8"), { filename: DATE_LABELS_JS });
const { formatShortDate, formatTime, formatFullDate } = global.window.RecipeDates;

function main() {
  const now = new Date(2026, 10, 28, 12, 0);
  const sameYear = new Date(2026, 10, 28, 9, 30);
  const otherYear = new Date(2025, 10, 28, 9, 30);

  assert.equal(formatShortDate(sameYear, now), "Nov 28");
  assert.equal(formatShortDate(otherYear, now), "Nov 28, 2025");
  assert.equal(formatTime(sameYear), "9:30 AM");
  assert.equal(formatFullDate("not-a-date"), "not-a-date");

  // Consumed by test/test_date_labels.py to check the Python fallback shape.
  console.log(
    JSON.stringify({
      sameYear: formatShortDate(sameYear, now),
      otherYear: formatShortDate(otherYear, now),
    }),
  );
}

main();
