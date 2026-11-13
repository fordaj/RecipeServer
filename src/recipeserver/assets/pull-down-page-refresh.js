// Pull-to-refresh indicator for touch devices. The styles live in
// pull-down-page-refresh.css, which both generators link alongside this script.

// Vertical distance the indicator spans sit above their resting position while
// hidden. The stylesheet positions them relative; the JS sets the offset so it
// is defined in exactly one place.
const INDICATOR_HIDDEN_OFFSET_PX = 56;

// Stretch applied to the raw pull distance so the indicator feels resistant
// rather than tracking the finger 1:1.
const PULL_DAMPING_FACTOR = 0.5;

// Delay between showing the "Refreshing…" state and reloading, so the user
// sees the indicator before the page navigates away.
const RELOAD_DELAY_MS = 150;

// Native <dialog> editors that make pull-to-refresh unsafe while open: the
// user is mid-edit, and reloading would discard in-progress changes. These
// IDs are owned by recipe-editor.js and config-editor.js; this module cannot
// import them, so the guarded selectors are named here instead of being raw
// literals scattered through the gesture handlers.
const GUARDED_DIALOG_IDS = ["recipe-markdown-editor", "config-editor"];

class PullToRefresh {
  constructor({ threshold = 100, maxPull = 90 } = {}) {
    this.threshold = threshold;
    this.maxPull = maxPull;

    this.startY = 0;
    this.pullDistance = 0;
    this.active = false;
    this.tracking = false;

    this.indicator = document.createElement("div");
    this.indicator.id = "pull-to-refresh";
    this.indicator.innerHTML = `
      <span class="ptr-arrow">↓</span>
      <span class="ptr-text">Pull to refresh</span>
    `;

    document.body.appendChild(this.indicator);

    this.arrow = this.indicator.querySelector(".ptr-arrow");
    this.text = this.indicator.querySelector(".ptr-text");

    this.setIndicatorOffset(-INDICATOR_HIDDEN_OFFSET_PX);

    this.addListeners();
  }

  isDisabled() {
    return GUARDED_DIALOG_IDS.some((dialogId) => document.getElementById(dialogId)?.open === true);
  }

  setIndicatorOffset(offsetPx) {
    const offset = `${offsetPx}px`;
    this.text.style.top = offset;
    this.arrow.style.top = offset;
  }

  addListeners() {
    document.addEventListener("touchstart", (event) => this.onTouchStart(event), { passive: true });

    document.addEventListener("touchmove", (event) => this.onTouchMove(event), { passive: false });

    document.addEventListener("touchend", () => this.onTouchEnd(), { passive: true });

    document.addEventListener("touchcancel", () => this.reset(), { passive: true });
  }

  onTouchStart(event) {
    if (this.isDisabled()) return;
    if (event.touches.length !== 1) return;
    if (window.scrollY > 0) return;

    this.startY = event.touches[0].clientY;
    this.pullDistance = 0;
    this.tracking = true;
    this.active = false;
  }

  onTouchMove(event) {
    // Completely disable pull-to-refresh while an editor is open.
    if (this.isDisabled()) {
      this.reset();
      return;
    }

    if (!this.tracking || event.touches.length !== 1) {
      return;
    }

    const currentY = event.touches[0].clientY;
    const deltaY = currentY - this.startY;

    // Only respond to a downward pull at the top.
    if (deltaY <= 0 || window.scrollY > 0) {
      if (this.active) {
        this.reset();
      } else {
        this.tracking = false;
      }
      return;
    }

    // Stop native scrolling / rubber-banding during our pull.
    event.preventDefault();

    this.active = true;

    // Dampen the movement for a natural feel.
    this.pullDistance = Math.min(deltaY * PULL_DAMPING_FACTOR, this.maxPull);

    this.setIndicatorOffset(this.pullDistance - INDICATOR_HIDDEN_OFFSET_PX);

    this.indicator.classList.add("ptr-active");

    const ready = deltaY >= this.threshold;

    this.indicator.classList.toggle("ptr-ready", ready);
    this.arrow.textContent = ready ? "↑" : "↓";
    this.text.textContent = ready ? "Release to refresh" : "Pull to refresh";
  }

  onTouchEnd() {
    if (!this.tracking) return;

    // Safety check in case an editor opened during the gesture.
    if (this.isDisabled()) {
      this.reset();
      return;
    }

    const shouldRefresh = this.active && this.indicator.classList.contains("ptr-ready");

    this.tracking = false;

    if (shouldRefresh) {
      this.indicator.classList.remove("ptr-active");
      this.indicator.classList.add("ptr-loading");

      this.arrow.textContent = "↻";
      this.text.textContent = "Refreshing…";

      this.setIndicatorOffset(0);

      // Allow the indicator to appear before reloading.
      setTimeout(() => location.reload(), RELOAD_DELAY_MS);
    } else {
      this.reset();
    }
  }

  reset() {
    this.tracking = false;
    this.active = false;
    this.pullDistance = 0;

    this.indicator.classList.remove("ptr-active", "ptr-ready", "ptr-loading");

    this.setIndicatorOffset(-INDICATOR_HIDDEN_OFFSET_PX);

    this.arrow.textContent = "↓";
    this.text.textContent = "Pull to refresh";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  new PullToRefresh();
});
