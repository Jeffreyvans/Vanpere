const EXT = { heic: "image/heic", heif: "image/heif", jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp" };

export function contentType(file) {
  if (file.type) return file.type.toLowerCase();
  return EXT[(file.name.split(".").pop() || "").toLowerCase()] || "";
}

/**
 * Resize (longest edge) and re-encode as JPEG, honouring EXIF orientation.
 * Formats the browser cannot decode (e.g. HEIC) are returned untouched for server conversion.
 */
export async function compress(file, { maxEdge, quality }) {
  if (!/^image\/(jpeg|png|webp)$/.test(contentType(file))) return file;
  let bitmap;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    return file;
  }
  const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height));
  const w = Math.round(bitmap.width * scale);
  const h = Math.round(bitmap.height * scale);
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, w, h);
  ctx.drawImage(bitmap, 0, 0, w, h);
  bitmap.close?.();
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
  return blob && blob.size < file.size ? blob : file;
}
