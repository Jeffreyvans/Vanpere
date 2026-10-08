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
  const tileEls = new Map();

  function placeMeta(p, tile) {
    if (!(p.likes || p.comments)) return;
    const meta = document.createElement("span");
    meta.className = "tile-meta";
    meta.setAttribute("aria-hidden", "true");
    const like = document.createElement("span");
    const comments = document.createElement("span");
    like.textContent = `${p.likes || 0} likes`;
    comments.textContent = `${p.comments || 0} comments`;
    meta.append(like, comments);
    tile.append(meta);
  }

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
    heights[k] += (p.w ? p.h / p.w : 1) || 1;
    const tile = document.createElement("button");
    tile.type = "button";
    tile.className = "tile loading";
    tile.style.aspectRatio = p.w && p.h ? `${p.w} / ${p.h}` : "4 / 3";
    tile.setAttribute("aria-label", `Open item ${index + 1}`);
    if (p.type === "video") {
      tile.classList.add("tile-video");
      if (p.thumb) {
        const img = document.createElement("img");
        img.loading = "lazy";
        img.alt = "";
        img.addEventListener("load", () => tile.classList.remove("loading"));
        img.addEventListener("error", () => tile.classList.remove("loading"));
        img.src = p.thumb;
        tile.append(img);
      } else {
        tile.classList.remove("loading");
      }
      const play = document.createElement("span");
      play.className = "tile-play";
      play.setAttribute("aria-hidden", "true");
      play.textContent = "\u25B6";
      tile.append(play);
    } else {
      const img = document.createElement("img");
      img.loading = "lazy";
      img.alt = "";
      img.addEventListener("load", () => tile.classList.remove("loading"));
      img.addEventListener("error", () => tile.classList.remove("loading"));
      img.src = p.thumb;
      tile.append(img);
    }
    placeMeta(p, tile);
    tile.addEventListener("click", () => viewer.open(photos.indexOf(p)));
    cols[k].append(tile);
    tileEls.set(p.id, tile);
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
    $("count").textContent = total ? `${total} item${total === 1 ? "" : "s"}` : "";
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

  function setCounts(id, patch) {
    const p = photos.find((x) => x.id === id);
    if (!p) return;
    Object.assign(p, patch);
    const tile = tileEls.get(id);
    if (!tile) return;
    const meta = tile.querySelector(".tile-meta");
    if (meta) {
      const spans = meta.children;
      spans[0].textContent = `${p.likes || 0} likes`;
      spans[1].textContent = `${p.comments || 0} comments`;
    } else if (p.likes || p.comments) {
      placeMeta(p, tile);
    }
  }

  const viewer = new Viewer({
    api, token, photos: () => photos, hasMore: () => !done, loadMore: load,
    shareUrl: root.dataset.share, name: root.dataset.name, setCounts,
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
