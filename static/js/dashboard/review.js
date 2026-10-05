// Keyboard-friendly quick review: A approve, R reject, S skip.
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const tag = (document.activeElement?.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") return;
  const key = e.key.toLowerCase();
  const target = { a: "approve", r: "reject", s: "skip" }[key];
  const el = target && document.getElementById(target);
  if (el) { e.preventDefault(); el.click(); }
});
