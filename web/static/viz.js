(async function () {
  const canvas  = document.getElementById("viz-canvas");
  const tooltip = document.getElementById("viz-tooltip");
  const status  = document.getElementById("viz-status");
  const ctx     = canvas.getContext("2d");

  // ── Fetch data ────────────────────────────────────────────────────
  let data;
  try {
    const res = await fetch("/api/viz");
    if (!res.ok) throw new Error("HTTP " + res.status);
    data = await res.json();
  } catch (err) {
    status.textContent = "Failed to load topic map: " + err.message;
    return;
  }

  const { entries, themes } = data;
  if (!entries || entries.length === 0) {
    status.textContent = "No visualization data yet — run a Refresh to generate the topic map.";
    canvas.style.display = "none";
    return;
  }

  status.textContent = entries.length + " articles · " + themes.length + " themes";

  // ── Color per feed_id ─────────────────────────────────────────────
  const feedColors = {};
  function _hue(id) {
    let h = (id * 2654435761) >>> 0;
    return h % 360;
  }
  function feedColor(feedId) {
    if (!feedColors[feedId]) {
      feedColors[feedId] = `hsl(${_hue(feedId)},65%,62%)`;
    }
    return feedColors[feedId];
  }

  // ── Coordinate mapping ────────────────────────────────────────────
  const xs = entries.map(e => e.viz_x);
  const ys = entries.map(e => e.viz_y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const PAD = 40;

  function toCanvas(x, y, w, h) {
    const cx = PAD + ((x - minX) / (maxX - minX)) * (w - PAD * 2);
    const cy = PAD + ((y - minY) / (maxY - minY)) * (h - PAD * 2);
    return [cx, cy];
  }

  // ── Draw ──────────────────────────────────────────────────────────
  function draw() {
    const dpr = window.devicePixelRatio || 1;
    const W   = canvas.parentElement.clientWidth;
    const narrow = W < 700;
    const H   = Math.min(W * (narrow ? 0.8 : 0.65), window.innerHeight * (narrow ? 0.75 : 0.72));
    canvas.width  = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width  = W + "px";
    canvas.style.height = H + "px";
    ctx.scale(dpr, dpr);

    ctx.clearRect(0, 0, W, H);

    // Dots
    for (const e of entries) {
      const [cx, cy] = toCanvas(e.viz_x, e.viz_y, W, H);
      ctx.beginPath();
      ctx.arc(cx, cy, narrow ? 4.5 : 3.5, 0, Math.PI * 2);
      ctx.fillStyle = feedColor(e.feed_id) + "cc";
      ctx.fill();
    }

    // Theme labels
    const isDark = !document.documentElement.hasAttribute("data-theme") ||
                   document.documentElement.getAttribute("data-theme") === "dark";
    ctx.font = `bold ${narrow ? 12 : 11}px -apple-system, BlinkMacSystemFont, sans-serif`;
    ctx.textAlign = "center";
    for (const t of themes) {
      const [cx, cy] = toCanvas(t.centroid_x, t.centroid_y, W, H);
      const label = t.label.split(" ").slice(0, 3).join(" · ");
      ctx.fillStyle = isDark ? "rgba(226,228,239,0.75)" : "rgba(26,29,46,0.75)";
      ctx.fillText(label, cx, cy);
    }
  }

  draw();
  window.addEventListener("resize", draw);

  // ── Tooltip ───────────────────────────────────────────────────────
  let _hoveredEntry = null;
  let _touchCandidate = null;
  let _suppressNextClick = false;

  function _showTooltip(entry, clientX, clientY) {
    tooltip.textContent = entry.title || "(no title)";
    tooltip.style.display = "block";
    const pad = 12;
    tooltip.style.left = "0px";
    tooltip.style.top = "0px";
    const box = tooltip.getBoundingClientRect();
    const left = Math.max(pad, Math.min(clientX + 14, window.innerWidth - box.width - pad));
    const top = Math.max(pad, Math.min(clientY - 10, window.innerHeight - box.height - pad));
    tooltip.style.left = left + "px";
    tooltip.style.top = top + "px";
  }

  function _hideTooltip() {
    tooltip.style.display = "none";
    _hoveredEntry = null;
    _touchCandidate = null;
  }

  function _findNearest(mx, my) {
    const W = canvas.clientWidth, H = canvas.clientHeight;
    let best = null, bestD = 14 * 14;
    for (const e of entries) {
      const [cx, cy] = toCanvas(e.viz_x, e.viz_y, W, H);
      const d = (cx - mx) ** 2 + (cy - my) ** 2;
      if (d < bestD) { bestD = d; best = e; }
    }
    return best;
  }

  canvas.addEventListener("mousemove", (ev) => {
    const rect = canvas.getBoundingClientRect();
    const mx = ev.clientX - rect.left;
    const my = ev.clientY - rect.top;
    const e = _findNearest(mx, my);
    if (e !== _hoveredEntry) {
      _hoveredEntry = e;
      if (e) {
        _showTooltip(e, ev.clientX, ev.clientY);
      } else {
        _hideTooltip();
      }
    }
    if (e) {
      _showTooltip(e, ev.clientX, ev.clientY);
    }
  });

  canvas.addEventListener("mouseleave", () => {
    _hideTooltip();
  });

  canvas.addEventListener("click", (ev) => {
    if (_suppressNextClick) {
      _suppressNextClick = false;
      return;
    }
    const rect = canvas.getBoundingClientRect();
    const mx = ev.clientX - rect.left;
    const my = ev.clientY - rect.top;
    const e = _findNearest(mx, my);
    if (e && e.link) window.open(e.link, "_blank", "noopener,noreferrer");
  });

  canvas.addEventListener("touchstart", (ev) => {
    const touch = ev.touches[0];
    if (!touch) return;
    const rect = canvas.getBoundingClientRect();
    const mx = touch.clientX - rect.left;
    const my = touch.clientY - rect.top;
    const e = _findNearest(mx, my);
    _touchCandidate = e || null;
    if (e) {
      _hoveredEntry = e;
      _showTooltip(e, touch.clientX, touch.clientY);
    } else {
      _hideTooltip();
    }
    ev.preventDefault();
  }, { passive: false });

  canvas.addEventListener("touchmove", (ev) => {
    const touch = ev.touches[0];
    if (!touch) return;
    const rect = canvas.getBoundingClientRect();
    const mx = touch.clientX - rect.left;
    const my = touch.clientY - rect.top;
    const e = _findNearest(mx, my);
    _touchCandidate = e || null;
    if (e) {
      _hoveredEntry = e;
      _showTooltip(e, touch.clientX, touch.clientY);
    } else {
      _hideTooltip();
    }
    ev.preventDefault();
  }, { passive: false });

  canvas.addEventListener("touchend", () => {
    if (_touchCandidate && _touchCandidate.link) {
      _suppressNextClick = true;
      window.open(_touchCandidate.link, "_blank", "noopener,noreferrer");
    }
    _touchCandidate = null;
  });
})();
