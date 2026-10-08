import { postJson } from "../upload/api.js";

const MAX_SCALE = 5;
const dist = (t) => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
const typing = (el) => ["input", "textarea", "select"].includes((el?.tagName || "").toLowerCase());

function timeAgo(iso) {
  const age = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!Number.isFinite(age)) return "";
  if (age < 60) return "just now";
  if (age < 3600) return `${Math.floor(age / 60)}m ago`;
  if (age < 86400) return `${Math.floor(age / 3600)}h ago`;
  if (age < 86400 * 30) return `${Math.floor(age / 86400)}d ago`;
  return new Date(iso).toLocaleDateString();
}

/** Full-screen photo viewer: swipe/keys, preload, pinch and double-tap zoom, share,
 * download, like, comments, report, delete. */
export class Viewer {
  constructor(ctx) {
    this.ctx = ctx;
    const $ = (id) => document.getElementById(id);
    this.el = $("viewer");
    this.img = $("v-img");
    this.video = $("v-video");
    this.status = $("v-status");
    this.reportForm = $("v-report");
    this.social = $("v-social");
    this.commentList = $("v-comments");
    this.commentForm = $("v-comment-form");
    this.commentName = $("v-comment-name");
    this.commentBody = $("v-comment-body");
    this.btn = { close: $("v-close"), prev: $("v-prev"), next: $("v-next"), share: $("v-share"),
      download: $("v-download"), like: $("v-like"), comments: $("v-comments-open"),
      report: $("v-report-open"), del: $("v-delete") };
    this.i = 0;
    this.scale = 1;
    this.pan = { x: 0, y: 0 };
    this.lastTap = 0;
    this.pinch = null;
    this.pinched = false;
    this.liked = false;
    this.likeCount = 0;
    this.likeBusy = false;
    this.commentCount = 0;
    this.commentsPhoto = null;
    this.bind($);
  }

  get photo() { return this.ctx.photos()[this.i]; }
  get isOpen() { return !this.el.hidden; }

  bind($) {
    const b = this.btn;
    b.close.addEventListener("click", () => this.close());
    b.prev.addEventListener("click", () => this.step(-1));
    b.next.addEventListener("click", () => this.step(1));
    b.share.addEventListener("click", () => this.share());
    b.like.addEventListener("click", () => this.like());
    b.comments.addEventListener("click", () => this.toggleComments());
    b.comments.addEventListener("keydown", (e) => { if (e.key === " " || e.key === "Enter") e.preventDefault(); });
    b.report.addEventListener("click", () => { this.reportForm.hidden = false; $("v-reason").focus(); });
    $("v-report-cancel").addEventListener("click", () => { this.reportForm.hidden = true; });
    this.reportForm.addEventListener("submit", (e) => { e.preventDefault(); this.report($("v-reason").value, $("v-note").value); });
    this.commentForm.addEventListener("submit", (e) => this.submitComment(e));
    b.del.addEventListener("click", () => this.remove());
    this.el.addEventListener("keydown", (e) => this.key(e));
    this.img.addEventListener("dblclick", () => this.setScale(this.scale > 1 ? 1 : 2.5));
    const stage = $("v-stage");
    stage.addEventListener("touchstart", (e) => this.touchStart(e), { passive: true });
    stage.addEventListener("touchmove", (e) => this.touchMove(e), { passive: true });
    stage.addEventListener("touchend", (e) => this.touchEnd(e));
    stage.addEventListener("touchcancel", () => { this.pinch = null; this.pinched = false; this.t0 = null; });
    // trackpad pinch (and ctrl + wheel) arrive as wheel events with ctrlKey set
    stage.addEventListener("wheel", (e) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      this.setScale(this.scale * Math.exp(-e.deltaY * 0.01), true);
    }, { passive: false });
  }

  open(i) {
    this.i = i;
    this.lastFocus = document.activeElement;
    this.el.hidden = false;
    document.body.classList.add("noscroll");
    this.show();
    this.btn.close.focus();
  }

  close() {
    this.el.hidden = true;
    document.body.classList.remove("noscroll");
    this.setScale(1);
    this.closeComments();
    this.lastFocus?.focus?.();
  }

  async show() {
    const photos = this.ctx.photos();
    const p = this.photo;
    if (!p) return this.close();
    this.setScale(1);
    if (p.type === "video") {
      this.img.hidden = true;
      this.img.removeAttribute("src");
      this.video.hidden = false;
      if (this.video.src !== p.video) {
        this.video.src = p.video;
        this.video.poster = p.thumb || "";
        this.video.load?.();
      }
      this.video.alt = "";
      this.img.alt = "";
    } else {
      this.video.hidden = true;
      this.video.pause?.();
      this.video.removeAttribute("src");
      this.video.load?.();
      this.img.hidden = false;
      this.img.src = p.medium;
      this.img.alt = `Photo ${this.i + 1} of ${photos.length}${p.name ? `, shared by ${p.name}` : ""}`;
    }
    this.btn.download.href = `${this.ctx.api}photos/${p.id}/download/`;
    this.btn.del.hidden = !p.mine;
    this.reportForm.hidden = true;
    this.commentBody.value = "";
    this.status.textContent = "";
    this.liked = Boolean(p.liked);
    this.likeCount = p.likes || 0;
    this.commentCount = p.comments || 0;
    this.updateSocial();
    this.closeComments();
    this.btn.prev.hidden = this.i === 0;
    const preload = (n) => { const t = photos[n]; if (t) new Image().src = t.medium || t.thumb || ""; };
    [this.i - 1, this.i + 1].forEach(preload);
    if (this.i >= photos.length - 3 && this.ctx.hasMore()) {
      await this.ctx.loadMore();
      preload(this.i + 1);
    }
    this.btn.next.hidden = this.i >= this.ctx.photos().length - 1 && !this.ctx.hasMore();
  }

  step(d) {
    const n = this.i + d;
    if (n < 0 || n >= this.ctx.photos().length) return;
    this.i = n;
    this.show();
  }

  key(e) {
    if (e.key === "Escape") return this.close();
    if (typing(e.target)) return;
    if (e.key === "l" || e.key === "L") return this.like();
    const panStep = 60;
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      const dir = e.key === "ArrowLeft" ? 1 : -1;
      if (this.scale > 1) { this.pan.x += dir * panStep; this.clampPan(); this.applyZoom(); } else this.step(-dir);
    } else if (e.key === "ArrowUp" && this.scale > 1) { this.pan.y += panStep; this.clampPan(); this.applyZoom(); }
    else if (e.key === "ArrowDown" && this.scale > 1) { this.pan.y -= panStep; this.clampPan(); this.applyZoom(); }
    else if (e.key === "+" || e.key === "=") this.setScale(this.scale * 1.5);
    else if (e.key === "-") this.setScale(this.scale / 1.5);
    else if (e.key === "0") this.setScale(1);
    else if (e.key === "Tab") {
      const f = [...this.el.querySelectorAll("button:not([hidden]), a[href], select, input, textarea")].filter((n) => !n.closest("[hidden]"));
      if (!f.length) return;
      const first = f[0];
      const last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  }

  // ---- zoom ----
  setScale(s, gesture = false) {
    this.scale = Math.min(MAX_SCALE, Math.max(1, s));
    if (this.scale === 1) this.pan = { x: 0, y: 0 };
    this.clampPan();
    this.applyZoom(gesture);
  }

  clampPan() {
    const mx = ((this.scale - 1) * this.img.clientWidth) / 2;
    const my = ((this.scale - 1) * this.img.clientHeight) / 2;
    this.pan.x = Math.max(-mx, Math.min(mx, this.pan.x));
    this.pan.y = Math.max(-my, Math.min(my, this.pan.y));
  }

  applyZoom(gesture = false) {
    this.img.style.transition = gesture ? "none" : "";
    this.img.style.transform = this.scale > 1 ? `translate(${this.pan.x}px, ${this.pan.y}px) scale(${this.scale})` : "";
  }

  // ---- touch: pinch to zoom, drag to pan, swipe to navigate, double-tap to zoom ----
  touchStart(e) {
    if (e.touches.length === 2) {
      this.pinch = { d: dist(e.touches), s: this.scale };
      this.pinched = true;
      this.t0 = null;
    } else if (e.touches.length === 1 && !this.pinched) {
      const t = e.touches[0];
      this.t0 = { x: t.clientX, y: t.clientY, px: this.pan.x, py: this.pan.y };
    }
  }

  touchMove(e) {
    if (e.touches.length === 2 && this.pinch) {
      this.setScale((this.pinch.s * dist(e.touches)) / this.pinch.d, true);
    } else if (this.scale > 1 && this.t0 && e.touches.length === 1) {
      const t = e.touches[0];
      this.pan = { x: this.t0.px + (t.clientX - this.t0.x), y: this.t0.py + (t.clientY - this.t0.y) };
      this.clampPan();
      this.applyZoom(true);
    }
  }

  touchEnd(e) {
    if (e.touches.length > 0) return; // other fingers still down
    if (this.pinched) {
      this.pinched = false;
      this.pinch = null;
      this.t0 = null;
      this.setScale(this.scale < 1.05 ? 1 : this.scale);
      return;
    }
    const t = e.changedTouches[0];
    if (!this.t0) return;
    const dx = t.clientX - this.t0.x;
    const dy = t.clientY - this.t0.y;
    this.t0 = null;
    if (Math.abs(dx) < 10 && Math.abs(dy) < 10) {
      const now = Date.now();
      if (now - this.lastTap < 300) this.setScale(this.scale > 1 ? 1 : 2.5);
      this.lastTap = now;
      return;
    }
    if (this.scale > 1) { this.applyZoom(); return; }
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) this.step(dx < 0 ? 1 : -1);
    else if (dy > 80 && Math.abs(dy) > Math.abs(dx)) this.close();
  }

  // ---- actions ----
  get photoLink() { return new URL(`p/${this.photo.id}/`, this.ctx.shareUrl).href; }

  async share() {
    const url = this.photoLink;
    if (navigator.share) {
      try { await navigator.share({ title: this.ctx.name, text: `A photo from ${this.ctx.name}`, url }); } catch { /* cancelled */ }
      return;
    }
    try { await navigator.clipboard.writeText(url); this.status.textContent = "Photo link copied."; }
    catch { this.status.textContent = url; }
  }

  async report(reason, note) {
    const p = this.photo;
    try {
      const res = await postJson(`${this.ctx.api}photos/${p.id}/report/`, this.ctx.token, { reason, note });
      this.reportForm.hidden = true;
      this.status.textContent = "Thank you. The organiser will review this photo.";
      if (res.hidden) this.dropCurrent();
    } catch (err) {
      this.status.textContent = err.status === 429 ? "Too many reports. Please try later." : "Could not send the report.";
    }
  }

  async remove() {
    const p = this.photo;
    if (!p?.mine || !window.confirm("Delete this photo for everyone?")) return;
    try {
      await postJson(`${this.ctx.api}photos/${p.id}/delete/`, this.ctx.token, {});
      this.dropCurrent();
    } catch {
      this.status.textContent = "Could not delete the photo.";
    }
  }

  dropCurrent() {
    this.ctx.remove(this.photo.id);
    const left = this.ctx.photos().length;
    if (!left) return this.close();
    this.i = Math.min(this.i, left - 1);
    this.show();
  }

  // ---- social: like ----
  updateSocial() {
    const likeBtn = this.btn.like;
    likeBtn.setAttribute("aria-pressed", this.liked ? "true" : "false");
    likeBtn.classList.toggle("on", this.liked);
    document.getElementById("v-likes").textContent = String(this.likeCount);
    document.getElementById("v-comment-n").textContent = String(this.commentCount);
  }

  async like() {
    const p = this.photo;
    if (this.likeBusy) return;
    this.likeBusy = true;
    try {
      const res = await postJson(`${this.ctx.api}photos/${p.id}/like/`, this.ctx.token, {});
      this.liked = Boolean(res.liked);
      this.likeCount = Number(res.count) || 0;
      this.updateSocial();
      this.ctx.setCounts?.(p.id, { likes: this.likeCount });
    } catch (err) {
      this.status.textContent = err.status === 429 ? "Too many likes. Please try later." : "Could not update the like.";
    } finally {
      this.likeBusy = false;
    }
  }

  // ---- social: comments ----
  toggleComments() {
    if (this.social.hidden) {
      this.social.hidden = false;
      this.btn.comments.setAttribute("aria-expanded", "true");
      this.loadComments();
      this.commentBody.focus();
    } else {
      this.closeComments();
    }
  }

  closeComments() {
    this.social.hidden = true;
    this.btn.comments.setAttribute("aria-expanded", "false");
    this.commentList.replaceChildren();
    this.commentsPhoto = null;
  }

  async loadComments() {
    const p = this.photo;
    this.commentsPhoto = p.id;
    const list = this.commentList;
    list.replaceChildren();
    const pending = document.createElement("p");
    pending.className = "vnote";
    pending.textContent = "Loading comments…";
    list.append(pending);
    try {
      const res = await fetch(`${this.ctx.api}photos/${p.id}/comments/?limit=100`,
        { headers: { "X-Device-Token": this.ctx.token }, credentials: "same-origin" });
      if (!res.ok) throw new Error();
      const data = await res.json();
      if (this.commentsPhoto !== p.id) return;
      this.commentCount = Number(data.count) || 0;
      this.updateSocial();
      this.renderComments(data.comments || []);
    } catch {
      list.replaceChildren();
      const err = document.createElement("p");
      err.className = "vnote";
      err.textContent = "Could not load comments.";
      list.append(err);
    }
  }

  renderComments(comments) {
    const list = this.commentList;
    list.replaceChildren();
    if (!comments.length) {
      const empty = document.createElement("p");
      empty.className = "vnote";
      empty.textContent = "No comments yet. Be the first to say something nice.";
      list.append(empty);
      return;
    }
    for (const c of comments) {
      const row = document.createElement("div");
      row.className = "vcomment";
      row.dataset.id = c.id;
      const meta = document.createElement("p");
      meta.className = "vcomment-meta";
      const who = document.createElement("strong");
      who.textContent = c.name || "Guest";
      const when = document.createElement("span");
      when.textContent = timeAgo(c.at);
      meta.append(who, when);
      const body = document.createElement("p");
      body.className = "vcomment-body";
      body.textContent = c.body;
      row.append(meta, body);
      if (c.mine) {
        const del = document.createElement("button");
        del.type = "button";
        del.className = "vbtn vcomment-del";
        del.textContent = "Delete";
        del.addEventListener("click", () => this.deleteComment(c.id, row));
        row.append(del);
      }
      list.append(row);
    }
  }

  async submitComment(e) {
    e.preventDefault();
    const body = this.commentBody.value.trim();
    if (!body) return;
    const p = this.photo;
    try {
      const res = await postJson(`${this.ctx.api}photos/${p.id}/comments/create/`,
        this.ctx.token, { name: this.commentName.value.trim(), body });
      this.commentBody.value = "";
      this.commentCount = Number(res.count) || this.commentCount;
      this.updateSocial();
      this.ctx.setCounts?.(p.id, { comments: this.commentCount });
      if (this.commentsPhoto === p.id) await this.loadComments();
      this.status.textContent = "Comment posted.";
    } catch (err) {
      this.status.textContent = err.status === 429 ? "Too many comments. Please try later."
        : err.status === 400 ? "That comment could not be posted." : "Could not post the comment.";
    }
  }

  async deleteComment(id, row) {
    const p = this.photo;
    try {
      await postJson(`${this.ctx.api}photos/${p.id}/comments/${id}/delete/`, this.ctx.token, {});
      row.remove();
      this.commentCount = Math.max(0, this.commentCount - 1);
      this.updateSocial();
      this.ctx.setCounts?.(p.id, { comments: this.commentCount });
      if (!this.commentList.querySelector(".vcomment")) this.renderComments([]);
      this.status.textContent = "Comment deleted.";
    } catch {
      this.status.textContent = "Could not delete the comment.";
    }
  }
}