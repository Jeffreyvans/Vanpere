"""Regression tests for the guest Like button (client side).

The failure these tests pin down: the viewer stored the like count in ``this.like``,
which shadowed the class method ``like()``. As soon as a photo was shown, clicking the
heart threw ``TypeError: this.like is not a function`` inside the event listener, so no
request was ever sent and neither the heart nor the count changed.

The source-level test always runs; the behavioural test runs the real ``viewer.js`` in
Node with a stub DOM whenever Node is installed.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from django.test import SimpleTestCase

JS_DIR = Path(__file__).resolve().parent.parent / "static" / "js"

HARNESS = r"""
import { Viewer } from "./js/gallery/viewer.js";

let els = new Map();
let listeners = new Map();
let calls = [];
let queue = [];
let replies = [];

function el(id) {
  const handlers = [];
  listeners.set(id, handlers);
  return {
    id, hidden: false, value: "", textContent: "", style: {}, dataset: {}, href: "#",
    alt: "", src: "", poster: "", tagName: "DIV", clientWidth: 100, clientHeight: 100,
    attrs: {},
    classList: { _s: new Set(),
      add(...c) { c.forEach((x) => this._s.add(x)); },
      remove(...c) { c.forEach((x) => this._s.delete(x)); },
      toggle(c, on) { on ? this._s.add(c) : this._s.delete(c); },
      contains(c) { return this._s.has(c); } },
    addEventListener(type, fn) { handlers.push({ type, fn }); },
    setAttribute(n, v) { this.attrs[n] = String(v); },
    getAttribute(n) { return this.attrs[n] ?? null; },
    removeAttribute(n) { delete this.attrs[n]; },
    focus() {},
    click() { handlers.filter((h) => h.type === "click").forEach((h) => h.fn({})); },
    replaceChildren() {}, append() {}, remove() {},
    querySelector() { return null; }, querySelectorAll() { return []; }, closest() { return null; },
    load() {}, pause() {},
  };
}
const get = (id) => { if (!els.has(id)) els.set(id, el(id)); return els.get(id); };

globalThis.document = {
  getElementById: get,
  createElement: (t) => { const e = el(`new:${t}`); e.tagName = t.toUpperCase(); return e; },
  body: el("body"), activeElement: null, addEventListener() {},
};
globalThis.window = { confirm: () => true, innerWidth: 1200 };
globalThis.innerWidth = 1200;
globalThis.Image = class { set src(v) {} };
globalThis.navigator = {};

globalThis.fetch = (url, opts) => {
  calls.push({ url, method: opts?.method });
  return new Promise((resolve) => {
    queue.push(() => resolve({ ok: true, status: 200, json: async () => replies.shift() }));
  });
};

const photo = (type) => ({
  id: "11111111-1111-1111-1111-111111111111",
  type, medium: "m.jpg", thumb: "t.jpg", video: "v.mp4", w: 100, h: 100,
  likes: 3, comments: 1, liked: false, mine: false,
});

let failures = 0;
const check = (label, cond, extra = "") => {
  console.log(`${cond ? "PASS" : "FAIL"}  ${label}${extra ? ` (${extra})` : ""}`);
  if (!cond) failures += 1;
};

function setup(type) {
  els = new Map(); listeners = new Map(); calls = []; queue = []; replies = [];
  const p = photo(type);
  const v = new Viewer({
    api: "/api/events/ABCD1234/", token: "a".repeat(32),
    photos: () => [p], hasMore: () => false, loadMore: async () => {},
    shareUrl: "/event/ABCD1234/gallery/", name: "Test Event",
    setCounts: () => {}, remove: () => {},
  });
  v.open(0);
  return v;
}
const flush = () => new Promise((r) => setTimeout(r, 5));
const settle = async () => { await flush(); queue.forEach((f) => f()); await flush(); };
const fire = (id, type, e = {}) => (listeners.get(id) || []).filter((h) => h.type === type).forEach((h) => h.fn(e));

for (const type of ["image", "video"]) {
  const v = setup(type);
  check(`${type}: like() still callable after show()`, typeof v.like === "function", typeof v.like);
  check(`${type}: initial count rendered`, get("v-likes").textContent === "3", get("v-likes").textContent);

  replies.push({ liked: true, count: 4 });
  fire("v-like", "click");
  await settle();
  check(`${type}: click POSTs the like endpoint`,
    calls.length === 1 && calls[0].method === "POST" &&
    calls[0].url === "/api/events/ABCD1234/photos/11111111-1111-1111-1111-111111111111/like/",
    JSON.stringify(calls[0] || null));
  check(`${type}: heart enters liked state`, get("v-like").classList.contains("on"));
  check(`${type}: aria-pressed true`, get("v-like").getAttribute("aria-pressed") === "true",
    get("v-like").getAttribute("aria-pressed"));
  check(`${type}: count uses the server value`, get("v-likes").textContent === "4", get("v-likes").textContent);

  replies.push({ liked: false, count: 3 });
  fire("v-like", "click");
  await settle();
  check(`${type}: second click unlikes`, !get("v-like").classList.contains("on"));
  check(`${type}: count decreases`, get("v-likes").textContent === "3", get("v-likes").textContent);

  const before = calls.length;
  replies.push({ liked: true, count: 4 });
  fire("v-like", "click");
  fire("v-like", "click");
  await settle();
  check(`${type}: rapid double click sends one request`, calls.length === before + 1, `${calls.length - before}`);
}

const v = setup("image");
fire("viewer", "keydown", { key: "l", target: { tagName: "DIV" } });
await settle();
check("keyboard: l likes", calls.length === 1, `${calls.length}`);
fire("viewer", "keydown", { key: "l", target: { tagName: "TEXTAREA" } });
await settle();
check("keyboard: l while typing does not like", calls.length === 1, `${calls.length}`);

console.log(failures ? `${failures} FAILURES` : "ALL PASS");
process.exit(failures ? 1 : 0);
"""


class LikeButtonJsTests(SimpleTestCase):
    def test_like_method_is_not_shadowed_by_state(self):
        src = (JS_DIR / "gallery" / "viewer.js").read_text(encoding="utf-8")
        self.assertNotRegex(
            src, r"this\.like\s*=",
            "viewer.js must not assign to this.like: it shadows the like() method, "
            "so clicking the heart throws 'this.like is not a function' and no request is sent.")
        self.assertIn("this.like()", src, "the like button/shortcut must call the like() method")
        self.assertIn("this.likeCount = p.likes", src, "the like count needs its own state field")

    @unittest.skipUnless(shutil.which("node"), "node is required to exercise the real viewer.js")
    def test_click_sends_request_and_updates_the_heart_and_count(self):
        node = shutil.which("node")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(JS_DIR, root / "js")
            (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
            (root / "harness.mjs").write_text(HARNESS, encoding="utf-8")
            proc = subprocess.run([node, "harness.mjs"], cwd=root, capture_output=True,
                                  text=True, timeout=120)
        self.assertEqual(
            proc.returncode, 0,
            f"like button harness failed\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
        self.assertIn("ALL PASS", proc.stdout)
