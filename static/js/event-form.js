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
}
