// Shared date/time label rules for the browser.
//
// The recipe metadata timestamps, the version-history dialog and the server's
// fallback text all use the same rule: month + day, plus the year only when the
// date is not in the current year. `now` is injectable for cross-language
// contract tests.

(function () {
  "use strict";

  function isCurrentYear(date, now = new Date()) {
    return date.getFullYear() === now.getFullYear();
  }

  function formatShortDate(date, now = new Date()) {
    const options = { month: "short", day: "numeric" };
    if (!isCurrentYear(date, now)) options.year = "numeric";
    return new Intl.DateTimeFormat("en-US", options).format(date);
  }

  function formatTime(date) {
    return new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(date);
  }

  function formatFullDate(iso) {
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
  }

  window.RecipeDates = { isCurrentYear, formatShortDate, formatTime, formatFullDate };
})();
