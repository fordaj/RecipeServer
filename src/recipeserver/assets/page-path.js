// The library-relative Markdown path for the page currently in the browser.
// Feedback, version history and the assistant each used their own copy.

(function () {
  "use strict";

  function markdownPathFromLocation() {
    const page = decodeURIComponent(window.location.pathname.replace(/^\/+/, ""));
    return page.replace(/\.html$/i, ".md");
  }

  function recipePathFromLocation() {
    // A recipe page embeds the metadata JSON; the index does not.
    return document.getElementById("recipe-metadata") ? markdownPathFromLocation() : null;
  }

  window.RecipePagePath = { markdownPathFromLocation, recipePathFromLocation };
})();
