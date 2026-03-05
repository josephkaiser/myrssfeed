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
    const H   = Math.min(W * 0.65, window.innerHeight * 0.72);
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
      ctx.arc(cx, cy, 3.5, 0, Math.PI * 2);
      ctx.fillStyle = feedColor(e.feed_id) + "cc";
      ctx.fill();
    }

    // Theme labels
    const isDark = !document.documentElement.hasAttribute("data-theme") ||
                   document.documentElement.getAttribute("data-theme") === "dark";
    ctx.font = "bold 11px -apple-system, BlinkMacSystemFont, sans-serif";
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

  function _findNearest(mx, my) {
    const dpr = window.devicePixelRatio || 1;
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
        tooltip.style.display = "block";
        tooltip.textContent = e.title || "(no title)";
      } else {
        tooltip.style.display = "none";
      }
    }
    if (e) {
      tooltip.style.left = (ev.clientX + 14) + "px";
      tooltip.style.top  = (ev.clientY - 10) + "px";
    }
  });

  canvas.addEventListener("mouseleave", () => {
    tooltip.style.display = "none";
    _hoveredEntry = null;
  });

  canvas.addEventListener("click", (ev) => {
    const rect = canvas.getBoundingClientRect();
    const mx = ev.clientX - rect.left;
    const my = ev.clientY - rect.top;
    const e = _findNearest(mx, my);
    if (e && e.link) window.open(e.link, "_blank", "noopener,noreferrer");
  });
})();
