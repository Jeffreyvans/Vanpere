export class ApiError extends Error {
  constructor(status, data) {
    super(data?.error || `HTTP ${status}`);
    this.status = status;
    this.data = data || {};
  }
}

export async function postJson(url, token, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Device-Token": token },
    body: JSON.stringify(body),
    credentials: "same-origin",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

/** XHR wrapper so uploads report progress. Rejects only on network failure. */
export function xhrSend(url, { method = "POST", body, headers = {}, onProgress }) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open(method, url);
    Object.entries(headers).forEach(([k, v]) => x.setRequestHeader(k, v));
    if (onProgress) x.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    x.onload = () => resolve({ status: x.status, text: x.responseText, headers: x.getAllResponseHeaders() });
    x.onerror = () => reject(new Error("network"));
    x.ontimeout = x.onerror;
    x.send(body);
  });
}
