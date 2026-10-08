/** SHA-256 digests. Huge originals are fingerprinted from head + tail slices so hashing
 * a 500 MB video never loads the whole file into memory. */
const MB = 1048576;
const FINGERPRINT_LIMIT = 64 * MB;
const TAIL_BYTES = 8 * MB;

const hex = (bytes) => Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");

async function digest(bytes) {
  if (!globalThis.crypto?.subtle) return "";
  return hex(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)));
}

/** Full-file SHA-256 for files up to 64 MB, otherwise a stable fingerprint of the file. */
export async function fileFingerprint(blob) {
  if (blob.size <= FINGERPRINT_LIMIT) return digest(await blob.arrayBuffer());
  const head = new Uint8Array(await blob.slice(0, TAIL_BYTES).arrayBuffer());
  const foot = new Uint8Array(await blob.slice(blob.size - TAIL_BYTES, blob.size).arrayBuffer());
  const full = new Uint8Array(head.byteLength + foot.byteLength);
  full.set(head, 0);
  full.set(foot, head.byteLength);
  return digest(full);
}