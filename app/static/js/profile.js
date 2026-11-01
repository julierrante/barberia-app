(() => {
  "use strict";

  const input = document.querySelector("[data-avatar-input]");
  const preview = document.querySelector("[data-avatar-image]");
  const fallback = document.querySelector("[data-avatar-fallback]");
  if (!input || !preview) return;

  input.addEventListener("change", () => {
    const file = input.files && input.files[0];
    if (!file) return;
    const objectUrl = URL.createObjectURL(file);
    preview.src = objectUrl;
    preview.hidden = false;
    if (fallback) fallback.hidden = true;
    preview.addEventListener(
      "load",
      () => URL.revokeObjectURL(objectUrl),
      { once: true }
    );
  });
})();
