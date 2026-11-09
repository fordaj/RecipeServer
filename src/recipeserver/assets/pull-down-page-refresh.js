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

    this.addStyles();
    this.addListeners();
  }

  isDisabled() {
    const editorDialog = document.getElementById("recipe-markdown-editor");
    const configDialog = document.getElementById("config-editor");
    return editorDialog?.open === true || configDialog?.open === true;
  }

  addStyles() {
    const style = document.createElement("style");

    style.textContent = `
#pull-to-refresh {
  position: fixed;
  z-index: 9999;
  top: 0;
  left: 0;
  width: 100%;
  height: 0;

  display: flex;
  align-items: flex-start;
  justify-content: center;

  background: transparent;
  color: #666666;
  font: 14px sans-serif;

  transform: translateY(0);
  transition: none;
  pointer-events: none;
}

#pull-to-refresh.ptr-active {
  transition: none;
}

#pull-to-refresh > span {
  position: relative;
  top: -56px;
}

#pull-to-refresh .ptr-arrow {
  display: inline-flex;
  align-items: center;
  justify-content: center;

  width: 40px;
  height: 40px;

  padding: 0;
  margin-right: 8px;

  background: rgba(255, 255, 255, 0.96);
  border-radius: 50%;

  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);

  font-size: 20px;
  line-height: 1;
  transition: transform 0.15s ease;
}

#pull-to-refresh .ptr-text {
  display: inline-block;

  padding: 10px 16px;

  background: rgba(255, 255, 255, 0.96);
  border-radius: 24px;

  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);

  font-size: 14px;
  line-height: 20px;
}

#pull-to-refresh.ptr-loading .ptr-arrow {
  animation: ptr-spin 0.7s linear infinite;
}

@keyframes ptr-spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  #pull-to-refresh,
  #pull-to-refresh .ptr-arrow {
    transition: none !important;
    animation: none !important;
  }
}
/* Dark mode */
@media (prefers-color-scheme: dark) {
  #pull-to-refresh {
    color: #d4d0ca;
  }

  #pull-to-refresh .ptr-arrow,
  #pull-to-refresh .ptr-text {
    background: rgba(42, 40, 37, 0.96);
    color: #e8e4de;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
  }
}
    `;

    document.head.appendChild(style);
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
    // Completely disable pull-to-refresh while the editor is open.
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
    this.pullDistance = Math.min(deltaY * 0.5, this.maxPull);

    const offset = `${-56 + this.pullDistance}px`;

    this.text.style.top = offset;
    this.arrow.style.top = offset;

    this.indicator.classList.add("ptr-active");

    const ready = deltaY >= this.threshold;

    this.indicator.classList.toggle("ptr-ready", ready);
    this.arrow.textContent = ready ? "↑" : "↓";
    this.text.textContent = ready ? "Release to refresh" : "Pull to refresh";
  }

  onTouchEnd() {
    if (!this.tracking) return;

    // Safety check in case the editor opened during the gesture.
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

      this.text.style.top = "0";
      this.arrow.style.top = "0";

      // Allow the indicator to appear before reloading.
      setTimeout(() => location.reload(), 150);
    } else {
      this.reset();
    }
  }

  reset() {
    this.tracking = false;
    this.active = false;
    this.pullDistance = 0;

    this.indicator.classList.remove("ptr-active", "ptr-ready", "ptr-loading");

    this.text.style.top = "-56px";
    this.arrow.style.top = "-56px";

    this.arrow.textContent = "↓";
    this.text.textContent = "Pull to refresh";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  new PullToRefresh();
});
