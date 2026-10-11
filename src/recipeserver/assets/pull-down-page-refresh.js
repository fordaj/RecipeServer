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

  background: rgba(255, 255, 255, 0.96);
  padding: 10px 16px;
  border-radius: 24px;

  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
}

#pull-to-refresh .ptr-arrow {
  display: inline-block;
  font-size: 20px;
  line-height: 20px;
  transition: transform 0.15s ease;
}

#pull-to-refresh .ptr-text {
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
    if (event.touches.length !== 1) return;
    if (window.scrollY > 0) return;

    this.startY = event.touches[0].clientY;
    this.pullDistance = 0;
    this.tracking = true;
    this.active = false;
  }

  onTouchMove(event) {
    if (!this.tracking || event.touches.length !== 1) {
      return;
    }

    const currentY = event.touches[0].clientY;
    const deltaY = currentY - this.startY;

    // Only respond to a downward pull at the top.
    if (deltaY <= 0 || window.scrollY > 0) {
      if (this.active) this.reset();
      else this.tracking = false;
      return;
    }

    // Stop native scrolling / rubber-banding during our pull.
    event.preventDefault();

    this.active = true;

    // Dampen the movement for a natural feel.
    this.pullDistance = Math.min(deltaY * 0.5, this.maxPull);

    const pill = this.indicator.querySelector(".ptr-text");
    const arrow = this.indicator.querySelector(".ptr-arrow");

    pill.style.top = `${-56 + this.pullDistance}px`;
    arrow.style.top = `${-56 + this.pullDistance}px`;

    this.indicator.classList.add("ptr-active");

    const ready = deltaY >= this.threshold;

    this.indicator.classList.toggle("ptr-ready", ready);
    this.arrow.textContent = ready ? "↑" : "↓";
    this.text.textContent = ready ? "Release to refresh" : "Pull to refresh";
  }

  onTouchEnd() {
    if (!this.tracking) return;

    const shouldRefresh =
      this.active &&
      this.pullDistance >= this.maxPull &&
      this.indicator.classList.contains("ptr-ready");

    this.tracking = false;

    if (shouldRefresh) {
      this.indicator.classList.remove("ptr-active");
      this.indicator.classList.add("ptr-loading");

      this.arrow.textContent = "↻";
      this.text.textContent = "Refreshing…";
      this.indicator.querySelector(".ptr-text").style.top = "0";
      this.indicator.querySelector(".ptr-arrow").style.top = "0";

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

    this.indicator.querySelector(".ptr-text").style.top = "-56px";
    this.indicator.querySelector(".ptr-arrow").style.top = "-56px";
    this.arrow.textContent = "↓";
    this.text.textContent = "Pull to refresh";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  new PullToRefresh();
});
