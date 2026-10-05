/** SHA-256 hex of a Blob; resolves "" where crypto.subtle is unavailable (non-secure context). */
export async function sha256Hex(blob) {
  if (!globalThis.crypto?.subtle) return "";
  const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}
