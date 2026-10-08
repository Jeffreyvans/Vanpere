const form = document.querySelector("[data-default-days]");
if (form) {
  const days = Number(form.dataset.defaultDays);
  const eventDate = document.getElementById("id_event_date");
  const expiresOn = document.getElementById("id_expires_on");
  const hint = document.getElementById("expiry-hint");
  const fmt = (d) => d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
  const update = () => {
    let d;
    if (expiresOn.value) {
      d = new Date(`${expiresOn.value}T00:00:00`);
    } else if (eventDate.value) {
      d = new Date(`${eventDate.value}T00:00:00`);
      d.setDate(d.getDate() + days);
    } else {
      hint.textContent = "";
      return;
    }
    hint.textContent = `Photos can be shared until the end of ${fmt(d)} (Africa/Harare).`;
  };
  form.addEventListener("input", update);
  form.addEventListener("change", update);
  update();

  // One click, one submission: lock the button while the POST is in flight.
  const btn = form.querySelector('button[type="submit"]');
  if (btn) {
    const idle = btn.textContent;
    const busy = form.dataset.submitLabel || "Saving...";
    const lock = () => {
      if (btn.disabled) return false;
      btn.disabled = true;
      btn.setAttribute("aria-busy", "true");
      btn.textContent = busy;
      return true;
    };
    form.addEventListener("submit", lock);
    window.addEventListener("pageshow", (e) => {
      if (!e.persisted) return;
      btn.disabled = false;
      btn.removeAttribute("aria-busy");
      btn.textContent = idle;
    });
  }
}
