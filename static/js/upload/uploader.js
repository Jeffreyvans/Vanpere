import { deviceToken, store, uuid } from "./device.js";
import { fileFingerprint } from "./hash.js";
import * as queue from "./queue.js";
import { ApiError, postJson, xhrSend } from "./api.js";

const root = document.getElementById("uploader");
if (root) start(root);

const EXT_MIME = { heic: "image/heic", heif: "image/heif", jpg: "image/jpeg", jpeg: "image/jpeg",
  png: "image/png", webp: "image/webp", mp4: "video/mp4", mov: "video/quicktime",
  webm: "video/webm", m4v: "video/m4v", "3gp": "video/3gpp" };

const mimeFromName = (name) => EXT_MIME[(name.split(".").pop() || "").toLowerCase()] || "";

function start(root) {
  const $ = (id) => document.getElementById(id);
  const api = root.dataset.api;
  const code = root.dataset.code;
  const imageBytes = Number(root.dataset.maxImage || root.dataset.maxMb) * 1048576;
  const videoBytes = Number(root.dataset.maxVideo) * 1048576;
  const maxPhotos = Number(root.dataset.maxPhotos);
  const partBytes = Math.round(Number(root.dataset.partMb || 8) * 1048576);
  const token = deviceToken();
  const list = $("items");
  const summary = $("summary");
  const lowBox = $("low-bw");
  const consentKey = `vp_consent_${code}`;
  const items = new Map();
  const CANCEL = Symbol("cancel");
  let active = 0;

  const limit = () => (lowBox.checked ? 1 : 2);

  const nameInput = $("guest-name");
  nameInput.value = store.get("vp_name") || "";
  nameInput.addEventListener("input", () => store.set("vp_name", nameInput.value));

  const conn = navigator.connection;
  if (conn && (conn.saveData || /^(slow-2g|2g|3g)$/.test(conn.effectiveType || ""))) {
    lowBox.checked = true;
    $("low-bw-note").hidden = false;
  }

  // ---- consent ----
  const showConsent = () => { $("consent").hidden = false; $("upload-area").hidden = true; };
  const showUpload = () => { $("consent").hidden = true; $("upload-area").hidden = false; };
  $("consent-check").addEventListener("change", (e) => { $("consent-accept").disabled = !e.target.checked; });
  $("consent-accept").addEventListener("click", async () => {
    try {
      await postJson(`${api}consent/`, token, {});
      store.set(consentKey, "1");
      showUpload();
      items.forEach((it) => { if (it.rec.status === "consent") it.rec.status = "queued"; });
      pump();
    } catch {
      summary.textContent = "Could not record your agreement. Check your connection and try again.";
      $("upload-area").hidden = false;
    }
  });

  // ---- UI ----
  const button = (label, onClick, hidden = false) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.hidden = hidden;
    b.addEventListener("click", onClick);
    return b;
  };

  function refreshSummary() {
    const all = [...items.values()];
    const done = all.filter((i) => i.rec.status === "done").length;
    const failed = all.filter((i) => i.rec.status === "failed").length;
    summary.textContent = all.length
      ? `${done} of ${all.length} shared${failed ? `, ${failed} need attention` : ""}.`
      : "";
  }

  function setStatus(it, text, state) {
    it.status.textContent = text;
    it.li.dataset.state = state;
    it.retry.hidden = state !== "failed";
    refreshSummary();
  }

  function render(it) {
    const li = document.createElement("li");
    li.className = "item";
    const thumb = document.createElement(it.rec.mediaType === "video" ? "div" : "img");
    thumb.className = "tile-thumb";
    if (it.rec.mediaType === "video") {
      thumb.textContent = "video";
    } else {
      const url = URL.createObjectURL(it.rec.blob);
      thumb.addEventListener("load", () => URL.revokeObjectURL(url));
      thumb.addEventListener("error", () => { thumb.hidden = true; URL.revokeObjectURL(url); });
      thumb.src = url;
    }
    const info = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = it.rec.name;
    it.status = document.createElement("span");
    it.status.className = "st";
    it.bar = document.createElement("progress");
    it.bar.max = 1;
    it.bar.value = 0;
    it.bar.setAttribute("aria-label", `Upload progress for ${it.rec.name}`);
    const lineBreak = () => document.createElement("br");
    info.append(name, lineBreak(), it.status, it.bar);
    const actions = document.createElement("div");
    it.retry = button("Retry", () => { it.rec.attempts = 0; it.rec.status = "queued"; setStatus(it, "Queued", "queued"); pump(); }, true);
    const remove = button("Remove", () => removeItem(it));
    actions.append(it.retry, remove);
    li.append(thumb, info, actions);
    it.li = li;
    list.append(li);
  }

  function removeItem(it) {
    it.cancelled = true;
    clearTimeout(it.timer);
    items.delete(it.rec.id);
    queue.remove(it.rec.id);
    if (it.rec.photoId && !["done", "failed"].includes(it.rec.status)) {
      postJson(`${api}uploads/${it.rec.photoId}/abort/`, token, {}).catch(() => {});
    }
    it.li.remove();
    refreshSummary();
  }

  // ---- queue ----
  function enqueue(rec) {
    const it = { rec, running: false, cancelled: false };
    items.set(rec.id, it);
    render(it);
    setStatus(it, "Queued", "queued");
    return it;
  }

  function addFiles(fileList) {
    const isImage = (f) => f.type.startsWith("image/") || /\.(heic|heif)$/i.test(f.name);
    const isVideo = (f) => f.type.startsWith("video/") || /\.(mov|mp4|webm|m4v|3gp)$/i.test(f.name);
    let files = [...fileList].filter((f) => isImage(f) || isVideo(f));
    if (files.length > maxPhotos) {
      summary.textContent = `Only the first ${maxPhotos} files were added (the limit per upload).`;
      files = files.slice(0, maxPhotos);
    }
    const batchId = uuid();
    files.forEach(async (file) => {
      const mediaType = isVideo(file) ? "video" : "image";
      const type = (file.type || mimeFromName(file.name)).toLowerCase();
      const rec = { id: uuid(), code, batchId, name: file.name, type, mediaType,
        blob: file, prepared: false, hash: "", photoId: "", uploadId: "", parts: [],
        presign: null, presignAt: 0, attempts: 0, status: "queued" };
      enqueue(rec);
      await queue.put(rec);
    });
    pump();
  }

  function pump() {
    if (store.get(consentKey) !== "1") return showConsent();
    for (const it of items.values()) {
      if (active >= limit()) break;
      if (it.rec.status === "queued" && !it.running) {
        it.running = true;
        active += 1;
        run(it).finally(() => { active -= 1; it.running = false; pump(); });
      }
    }
  }

  const MESSAGES = {
    too_large: (d) => `Too large (max ${d.limit_mb} MB).`,
    invalid_image: () => "That file is not a usable photo or video.",
    event_ended: () => "This event has ended.",
    uploads_disabled: () => "Uploads are turned off.",
    too_many: () => "Too many files in one upload.",
    unsupported_type: () => "Unsupported file type.",
  };

  function fail(it, text) {
    it.rec.status = "failed";
    setStatus(it, text, "failed");
    queue.put(it.rec);
  }

  function transient(it) {
    const r = it.rec;
    r.attempts += 1;
    if (r.attempts > 8) return fail(it, "Upload failed. Tap Retry.");
    r.status = "retry";
    setStatus(it, "Waiting to retry…", "retry");
    if (navigator.onLine) {
      it.timer = setTimeout(() => { r.status = "queued"; pump(); },
        Math.min(30000, 1000 * 2 ** r.attempts) + Math.random() * 500);
    }
  }

  function done(it, text) {
    it.rec.status = "done";
    it.bar.value = 1;
    setStatus(it, text, "done");
    queue.remove(it.rec.id);
  }

  async function uploadToStorage(it, alive) {
    const r = it.rec;
    if (r.mediaType === "video" && r.uploadId) {
      const total = Math.max(1, Math.ceil(r.blob.size / partBytes));
      r.parts = [];
      for (let n = 1; n <= total; n += 1) {
        alive();
        let url;
        try {
          const p = await postJson(`${api}uploads/${r.photoId}/part/`, token,
            { upload_id: r.uploadId, part: n });
          url = p.url;
        } catch (err) {
          if (err instanceof ApiError && err.data.error === "multipart_unavailable") return serverUpload(it, alive);
          throw err;
        }
        const res = await xhrSend(url, {
          method: "PUT", body: r.blob.slice((n - 1) * partBytes, n * partBytes),
        });
        if (res.status < 200 || res.status >= 300) {
          let detail = {};
          try { detail = JSON.parse(res.text || "{}"); } catch { detail = { error: res.text }; }
          throw new ApiError(res.status, detail);
        }
        const m = /etag:\s*(?:"([^"]+)"|([^\s;]+))/i.exec(res.headers || "");
        const etag = (m && (m[1] || m[2])) || "";
        r.parts.push({ n, e: etag });
        it.bar.value = n / total;
      }
      await queue.put(r);
      return;
    }
    if (r.presign && Date.now() - r.presignAt < 540000) {
      try {
        const res = await xhrSend(r.presign.url,
          { method: "PUT", body: r.blob, headers: r.presign.headers, onProgress: (p) => { it.bar.value = p; } });
        if (res.status >= 200 && res.status < 300) return;
      } catch { /* CORS or network problem: use the server fallback */ }
      r.presign = null;
    }
    await serverUpload(it, alive);
  }

  async function serverUpload(it, alive) {
    alive();
    const r = it.rec;
    const form = new FormData();
    form.append("file", r.blob, "upload." + (r.mediaType === "video" ? (r.type.split("/")[1] || "mp4") : "jpg"));
    const res = await xhrSend(`${api}uploads/${r.photoId}/file/`, {
      method: "POST", body: form, headers: { "X-Device-Token": token }, onProgress: (p) => { it.bar.value = p; } });
    if (res.status < 200 || res.status >= 300) {
      throw new ApiError(res.status, JSON.parse(res.text || "{}"));
    }
  }

  /** Best-effort first-frame poster for a video, captured client-side (no server ffmpeg). */
  function makePoster(file) {
    return new Promise((resolve) => {
      let url;
      let video;
      const settle = (blob) => { URL.revokeObjectURL(url); video?.removeAttribute("src"); resolve(blob); };
      const timer = setTimeout(() => settle(null), 10000);
      try {
        url = URL.createObjectURL(file);
        video = document.createElement("video");
        video.muted = true;
        video.playsInline = true;
        video.preload = "metadata";
        video.src = url;
        const timeout = timer;
        video.onloadedmetadata = () => { try { video.currentTime = 0.1; } catch { } };
        video.onseeked = () => {
          try {
            const c = document.createElement("canvas");
            c.width = 960;
            c.height = video.videoHeight && video.videoWidth
              ? Math.max(1, Math.round(960 * video.videoHeight / video.videoWidth)) : 540;
            c.getContext("2d").drawImage(video, 0, 0, c.width, c.height);
            c.toBlob((blob) => { clearTimeout(timeout); settle(blob); }, "image/webp", 0.72);
          } catch { clearTimeout(timeout); settle(null); }
        };
        video.onerror = () => { clearTimeout(timeout); settle(null); };
      } catch { clearTimeout(timer); settle(null); }
    });
  }

  async function attachPoster(it) {
    const blob = await makePoster(it.rec.blob);
    if (!blob) return;
    const form = new FormData();
    form.append("file", blob, "poster.webp");
    const res = await xhrSend(`${api}uploads/${it.rec.photoId}/poster/`, {
      method: "POST", body: form, headers: { "X-Device-Token": token } });
    if (res.status < 200 || res.status >= 300) throw new ApiError(res.status, {});
  }

  async function run(it) {
    const r = it.rec;
    const alive = () => { if (it.cancelled) throw CANCEL; };
    try {
      if (!r.prepared) {
        setStatus(it, "Preparing…", "working");
        const max = r.mediaType === "video" ? videoBytes : imageBytes;
        if (r.blob.size > max) return fail(it, `Too large (max ${max / 1048576} MB).`);
        r.hash = await fileFingerprint(r.blob);
        r.prepared = true;
        await queue.put(r);
      }
      alive();
      if (r.hash && (await postJson(`${api}check-hash/`, token, { hash: r.hash })).exists) {
        return done(it, "Already shared");
      }
      alive();
      if (!r.photoId) {
        const init = await postJson(`${api}uploads/init/`, token, {
          media_type: r.mediaType, content_type: r.type, size: r.blob.size, hash: r.hash,
          batch_id: r.batchId, name: nameInput.value });
        if (init.duplicate) return done(it, "Already shared");
        r.photoId = init.photo_id;
        r.uploadId = (init.multipart && init.multipart.upload_id) || "";
        r.presign = init.upload;
        r.presignAt = Date.now();
        await queue.put(r);
      }
      alive();
      setStatus(it, "Uploading…", "working");
      await uploadToStorage(it, alive);
      alive();
      setStatus(it, "Processing…", "working");
      const res = await postJson(`${api}uploads/${r.photoId}/finalise/`, token, r.parts.length ? { parts: r.parts } : {});
      alive();
      if (r.mediaType === "video") {
        try { await attachPoster(it); } catch { /* poster is optional */ }
        alive();
      }
      done(it, res.duplicate ? "Already shared" : res.status === "pending" ? "Shared (awaiting approval)" : "Shared");
    } catch (err) {
      if (err === CANCEL) return;
      if (err instanceof ApiError) {
        if (err.data.error === "consent_required") {
          store.set(consentKey, "0");
          r.status = "consent";
          setStatus(it, "Waiting for your agreement", "queued");
          return showConsent();
        }
        if (![429, 500, 502, 503, 504].includes(err.status)) {
          const msg = MESSAGES[err.data.error];
          return fail(it, msg ? msg(err.data) : "Upload failed. Tap Retry.");
        }
      }
      transient(it);
    }
  }

  // ---- inputs ----
  const pick = (e) => { addFiles(e.target.files); e.target.value = ""; };
  $("file-input").addEventListener("change", pick);
  $("camera-input").addEventListener("change", pick);
  const zone = $("dropzone");
  ["dragenter", "dragover"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.remove("over"); }));
  zone.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));

  window.addEventListener("online", () => {
    items.forEach((it) => {
      if (it.rec.status === "retry") { clearTimeout(it.timer); it.rec.attempts = 0; it.rec.status = "queued"; }
    });
    pump();
  });
  lowBox.addEventListener("change", pump);

  // Offline shell: caches this page and its scripts so the page still opens on a flaky connection.
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/event/sw.js", { scope: "/event/" }).catch(() => {});
  }

  // ---- resume anything left from an earlier visit ----
  if (store.get(consentKey) === "1") showUpload(); else showConsent();
  queue.all().then((saved) => {
    saved.filter((r) => r.code === code && r.status !== "done").forEach((r) => {
      r.status = "queued";
      r.attempts = 0;
      enqueue(r);
    });
    pump();
  });
}