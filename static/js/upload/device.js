const KEY = "vp_device";

export const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
};

const hex = (bytes) => Array.from(bytes, (x) => x.toString(16).padStart(2, "0"));

export function uuid() {
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 15) | 64;
  b[8] = (b[8] & 63) | 128;
  const h = hex(b);
  return `${h.slice(0, 4).join("")}-${h.slice(4, 6).join("")}-${h.slice(6, 8).join("")}-${h.slice(8, 10).join("")}-${h.slice(10).join("")}`;
}

/** Random per-device token kept in localStorage and a cookie (used to delete own uploads). */
export function deviceToken() {
  let t = store.get(KEY);
  if (!t) {
    const m = document.cookie.match(/(?:^|; )vp_device=([A-Za-z0-9_-]+)/);
    t = m ? m[1] : hex(crypto.getRandomValues(new Uint8Array(24))).join("");
  }
  store.set(KEY, t);
  document.cookie = `vp_device=${t}; Max-Age=31536000; Path=/; SameSite=Lax${location.protocol === "https:" ? "; Secure" : ""}`;
  return t;
}
