(() => {
  const currentYear = new Date().getFullYear();

  const dateFormatter = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  });

  const dateWithYearFormatter = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });

  function localizeTime(element) {
    const timestamp = element.getAttribute("datetime");
    if (!timestamp) return;

    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) return;

    const formatter = date.getFullYear() === currentYear ? dateFormatter : dateWithYearFormatter;
    const prefix = element.dataset.timePrefix || "";

    element.textContent = `${prefix}${formatter.format(date)}`;
    element.title = date.toLocaleString();
  }

  document.querySelectorAll("time[data-local-time]").forEach(localizeTime);
})();
