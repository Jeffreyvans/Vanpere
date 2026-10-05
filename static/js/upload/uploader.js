import { deviceToken, store, uuid } from "./device.js";
import { sha256Hex } from "./hash.js";
import { compress, contentType } from "./compress.js";
import * as queue from "./queue.js";
import { ApiError, postJson, xhrSend } from "./api.js";

const root = document.getElementById("uploader");
if (root) start(root);

function start(root) {
  const $ = (id) => document.getElementById(id);
  const api = root.dataset.api;
  const code = root.dataset.code;
  const maxBytes = Number(root.dataset.maxMb) * 1048576;
  const maxPhotos = Number(root.dataset.maxPhotos);
  const token = deviceToken();
  const list = $("items");
  const summary = $("summary");
  const lowBox = $("low-bw");
  const consentKey = `vp_consent_${code}`;
  const items = new Map();
  const CANCEL = Symbol("cancel");
  let active = 0;

  const limit = () => (lowBox.checked ? 1 : 2);
  const settings = () => (lowBox.checked ? { maxEdge: 1600, quality: 0.7 } : { maxEdge: 2560, quality: 0.82 });

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
      ? `${done} of ${all.length} photos shared${failed ? `, ${failed} need attention` : ""}.`
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
    const img = document.createElement("img");
    img.alt = "";
    it.url = URL.createObjectURL(it.rec.blob);
    img.addEventListener("load", () => URL.revokeObjectURL(it.url));
    img.addEventListener("error", () => { img.hidden = true; URL.revokeObjectURL(it.url); });
    img.src = it.url;
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
    li.append(img, info, actions);
    it.li = li;
    list.append(li);
  }

  function removeItem(it) {
    it.cancelled = true;
    clearTimeout(it.timer);
    items.delete(it.rec.id);
    queue.remove(it.rec.id);
    URL.revokeObjectURL(it.url);
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
    let files = [...fileList].filter((f) => f.type.startsWith("image/") || /\.(heic|heif)$/i.test(f.name));
    if (files.length > maxPhotos) {
      summary.textContent = `Only the first ${maxPhotos} photos were added (the limit per upload).`;
      files = files.slice(0, maxPhotos);
    }
    const batchId = uuid();
    files.forEach(async (file) => {
      const rec = { id: uuid(), code, batchId, name: file.name, type: contentType(file), blob: file,
        prepared: false, hash: "", photoId: "", presign: null, presignAt: 0, attempts: 0, status: "queued" };
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
    invalid_image: () => "That file is not a usable photo.",
    event_ended: () => "This event has ended.",
    uploads_disabled: () => "Uploads are turned off.",
    too_many: () => "Too many photos in one upload.",
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

  async function uploadToStorage(it) {
    const r = it.rec;
    const onProgress = (p) => { it.bar.value = p; };
    if (r.presign && Date.now() - r.presignAt < 540000) {
      try {
        const res = await xhrSend(r.presign.url, { method: "PUT", body: r.blob, headers: r.presign.headers, onProgress });
        if (res.status >= 200 && res.status < 300) return;
      } catch { /* CORS or network problem: use the server fallback */ }
      r.presign = null;
    }
    const form = new FormData();
    form.append("file", r.blob, "photo.jpg");
    const res = await xhrSend(`${api}uploads/${r.photoId}/file/`, {
      method: "POST", body: form, headers: { "X-Device-Token": token }, onProgress });
    if (res.status < 200 || res.status >= 300) {
      throw new ApiError(res.status, JSON.parse(res.text || "{}"));
    }
  }

  async function run(it) {
    const r = it.rec;
    const alive = () => { if (it.cancelled) throw CANCEL; };
    try {
      if (!r.prepared) {
        setStatus(it, "Compressing…", "working");
        r.blob = await compress(r.blob, settings());
        alive();
        if (r.blob.size > maxBytes) return fail(it, `Too large (max ${maxBytes / 1048576} MB).`);
        r.hash = await sha256Hex(r.blob);
        r.type = r.blob.type === "image/jpeg" ? "image/jpeg" : r.type || contentType(r.blob);
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
          content_type: r.type, size: r.blob.size, hash: r.hash, batch_id: r.batchId, name: nameInput.value });
        if (init.duplicate) return done(it, "Already shared");
        r.photoId = init.photo_id;
        r.presign = init.upload;
        r.presignAt = Date.now();
        await queue.put(r);
      }
      alive();
      setStatus(it, "Uploading…", "working");
      await uploadToStorage(it);
      alive();
      setStatus(it, "Processing…", "working");
      const res = await postJson(`${api}uploads/${r.photoId}/finalise/`, token, {});
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
