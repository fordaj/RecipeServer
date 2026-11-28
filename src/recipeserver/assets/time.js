(() => {
  const { formatShortDate, formatFullDate } = window.RecipeDates;

  function localizeTime(element) {
    const timestamp = element.getAttribute("datetime");
    if (!timestamp) return;

    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) return;

    const prefix = element.dataset.timePrefix || "";
    element.textContent = `${prefix}${formatShortDate(date)}`;
    element.title = formatFullDate(timestamp);
  }

  document.querySelectorAll("time[data-local-time]").forEach(localizeTime);
})();
