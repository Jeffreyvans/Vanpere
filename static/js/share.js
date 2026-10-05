const status = document.querySelector("[data-share-status]");
const say = (msg) => { if (status) status.textContent = msg; };

document.querySelectorAll("[data-copy]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const text = btn.dataset.copy;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      ta.remove();
      if (!ok) return say("Could not copy. Please copy the link manually.");
    }
    say("Link copied.");
  });
});

document.querySelectorAll("[data-native-share]").forEach((btn) => {
  if (!navigator.share) return;
  btn.hidden = false;
  btn.addEventListener("click", () => {
    navigator.share({ title: btn.dataset.title, text: btn.dataset.text, url: btn.dataset.url }).catch(() => {});
  });
});
