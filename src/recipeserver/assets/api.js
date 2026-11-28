// Shared JSON API wrapper for the page scripts.
//
// Every editor, dialog and assistant bundle used to repeat the same fetch /
// json / error-unwrap sequence, and a few forgot `.catch` on a non-JSON error
// response. One wrapper keeps the browser's error messages consistent.

(function () {
  "use strict";

  function responseError(response, result, fallbackMessage) {
    const message =
      result && result.error ? result.error : `${fallbackMessage} (HTTP ${response.status})`;
    const error = new Error(message);
    error.status = response.status;
    return error;
  }

  async function throwResponseError(response, fallbackMessage = "Request failed") {
    const result = await response.json().catch(() => ({}));
    throw responseError(response, result, fallbackMessage);
  }

  async function requestJson(url, options = {}) {
    const { expectSuccess = false, fallbackMessage = "Request failed", ...init } = options;
    const response = await fetch(url, init);
    const result = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw responseError(response, result, fallbackMessage);
    }
    if (expectSuccess && (!result || result.success !== true)) {
      throw new Error(fallbackMessage);
    }

    return result;
  }

  window.RecipeApi = { requestJson, throwResponseError };
})();
