import { deviceToken } from "../upload/device.js";
import { Viewer } from "./viewer.js";

const root = document.getElementById("gallery");
if (root) start(root);

function start(root) {
  const $ = (id) => document.getElementById(id);
  const api = root.dataset.api;
  const token = deviceToken();
  const colsEl = $("columns");
  const moreBtn = $("more");
  const photos = [];
  let cursor = null;
  let done = false;
  let loading = false;
  let total = 0;
  let colCount = 0;
  let cols = [];
  let heights = [];

  const want = () => (innerWidth >= 1000 ? 4 : innerWidth >= 700 ? 3 : 2);

  function makeColumns() {
    colCount = want();
    colsEl.replaceChildren();
    cols = Array.from({ length: colCount }, () => {
      const d = document.createElement("div");
      d.className = "mcol";
      colsEl.append(d);
      return d;
    });
    heights = Array(colCount).fill(0);
  }

  function place(p, index) {
    const k = heights.indexOf(Math.min(...heights));
    heights[k] += p.h / p.w;
    const tile = document.createElement("button");
    tile.type = "button";
    tile.className = "tile loading";
    tile.style.aspectRatio = `${p.w} / ${p.h}`;
    tile.setAttribute("aria-label", `Open photo ${index + 1}`);
    const img = document.createElement("img");
    img.loading = "lazy";
    img.alt = "";
    img.addEventListener("load", () => tile.classList.remove("loading"));
    img.addEventListener("error", () => tile.classList.remove("loading"));
    img.src = p.thumb;
    tile.append(img);
    tile.addEventListener("click", () => viewer.open(photos.indexOf(p)));
    cols[k].append(tile);
  }

  function layout() {
    makeColumns();
    photos.forEach(place);
    if (!photos.length && !done) {
      cols.forEach((c) => { for (let i = 0; i < 3; i += 1) {
        const s = document.createElement("div");
        s.className = "skel";
        s.style.aspectRatio = i % 2 ? "3 / 4" : "4 / 3";
        c.append(s);
      } });
    }
  }

  function refreshUi() {
    $("count").textContent = total ? `${total} photo${total === 1 ? "" : "s"}` : "";
    $("empty").hidden = !(done && photos.length === 0);
    moreBtn.hidden = done;
  }

  async function load() {
    if (loading || done) return;
    loading = true;
    try {
      const qs = new URLSearchParams({ limit: "24" });
      if (cursor) qs.set("cursor", cursor);
      const res = await fetch(`${api}photos/?${qs}`, { headers: { "X-Device-Token": token }, credentials: "same-origin" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        const msg = { pin_required: "Enter the PIN to see this gallery.", event_ended: "This event has ended." }[data.error];
        $("error").textContent = msg || "Could not load the gallery. Please try again.";
        $("error").hidden = false;
        done = true;
        return;
      }
      $("error").hidden = true;
      const data = await res.json();
      const start = photos.length;
      photos.push(...data.photos);
      total = data.count;
      cursor = data.next;
      done = !cursor;
      if (start === 0) layout(); else data.photos.forEach((p, i) => place(p, start + i));
    } catch {
      $("error").textContent = "Network problem. Tap Load more to try again.";
      $("error").hidden = false;
    } finally {
      loading = false;
      refreshUi();
      if ("IntersectionObserver" in window) { io.unobserve(sentinel); io.observe(sentinel); }
    }
  }

  const viewer = new Viewer({
    api, token, photos: () => photos, hasMore: () => !done, loadMore: load,
    shareUrl: root.dataset.share, name: root.dataset.name,
    remove: (id) => {
      const i = photos.findIndex((p) => p.id === id);
      if (i >= 0) { photos.splice(i, 1); total = Math.max(0, total - 1); layout(); refreshUi(); }
    },
  });

  const sentinel = $("sentinel");
  const io = "IntersectionObserver" in window
    ? new IntersectionObserver((entries) => { if (entries[0].isIntersecting) load(); }, { rootMargin: "600px" })
    : null;
  moreBtn.addEventListener("click", load);

  let timer;
  addEventListener("resize", () => {
    clearTimeout(timer);
    timer = setTimeout(() => { if (want() !== colCount) layout(); }, 150);
  });

  makeColumns();
  layout();
  load();
}
