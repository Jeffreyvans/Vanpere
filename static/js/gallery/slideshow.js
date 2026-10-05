const root = document.getElementById("show");
if (root) start(root);

function start(root) {
  const api = root.dataset.api;
  let interval = Number(root.dataset.interval) * 1000;
  const layers = [document.getElementById("a"), document.getElementById("b")];
  const empty = document.getElementById("empty");
  let top = 1;
  let photos = [];
  let idx = -1;
  let timer;

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(advance, interval);
  }

  function swap(p, next) {
    const incoming = layers[1 - top];
    incoming.src = p.medium;
    incoming.classList.add("on");
    layers[top].classList.remove("on");
    top = 1 - top;
    idx = next;
    schedule();
  }

  function show(next) {
    const p = photos[next];
    if (!p) return;
    const probe = new Image();
    probe.onload = () => swap(p, next);
    probe.onerror = () => { poll(); schedule(); }; // URL may have expired; refresh and move on
    probe.src = p.medium;
  }

  function advance() {
    if (photos.length > 1 || idx < 0) show((idx + 1) % Math.max(photos.length, 1));
    else schedule();
  }

  async function poll() {
    try {
      const res = await fetch(`${api}slideshow/`, { credentials: "same-origin", cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json();
      const current = photos[idx];
      const incoming = new Map(data.photos.map((p) => [p.id, p]));
      photos = photos.filter((p) => incoming.has(p.id)).map((p) => ({ ...p, medium: incoming.get(p.id).medium }));
      const known = new Set(photos.map((p) => p.id));
      const fresh = data.photos.filter((p) => !known.has(p.id));
      const pos = current ? photos.findIndex((p) => p.id === current.id) : -1;
      if (pos >= 0 || !photos.length) photos.splice(pos + 1, 0, ...fresh);
      else photos.push(...fresh);
      idx = current ? photos.findIndex((p) => p.id === current.id) : idx;
      empty.hidden = photos.length > 0;
      if (photos.length && idx < 0 && !timer) advance();
      else if (photos.length && !timer) advance();
    } catch { /* offline: keep showing what we have */ }
  }

  // controls: interval, skip, fullscreen
  document.addEventListener("keydown", (e) => {
    if (e.key === "+" || e.key === "=") interval = Math.min(30000, interval + 2000);
    else if (e.key === "-") interval = Math.max(3000, interval - 2000);
    else if (e.key === "ArrowRight") advance();
    else if (e.key === "ArrowLeft" && photos.length) show((idx - 1 + photos.length) % photos.length);
    else if (e.key === "f") document.documentElement.requestFullscreen?.();
  });
  document.getElementById("fs").addEventListener("click", () => document.documentElement.requestFullscreen?.());

  // hide cursor and controls after inactivity
  let idle;
  const wake = () => {
    document.body.classList.remove("idle");
    clearTimeout(idle);
    idle = setTimeout(() => document.body.classList.add("idle"), 3000);
  };
  ["mousemove", "keydown", "touchstart"].forEach((t) => document.addEventListener(t, wake, { passive: true }));
  wake();

  // keep the screen awake where supported
  const lock = async () => { try { await navigator.wakeLock?.request("screen"); } catch { /* unsupported or denied */ } };
  lock();
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") lock(); });

  poll();
  setInterval(poll, 20000);
}
