// Select-all and confirmation prompts for dashboard forms.
const all = document.getElementById("select-all");
if (all) {
  all.addEventListener("click", () => {
    const boxes = [...document.querySelectorAll("#bulk input[name=ids]")];
    const check = boxes.some((b) => !b.checked);
    boxes.forEach((b) => { b.checked = check; });
  });
}
document.querySelectorAll("[data-confirm]").forEach((btn) => {
  btn.addEventListener("click", (e) => { if (!window.confirm(btn.dataset.confirm)) e.preventDefault(); });
});
