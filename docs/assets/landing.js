// The only script on the landing page: copy the quickstart commands.
// No network requests, no analytics, no inline event handlers.

(() => {
  const button = document.querySelector("[data-copy-target]");
  if (!button) return;

  const target = document.getElementById(button.dataset.copyTarget);
  if (!target) return;

  let resetTimer;

  const setLabel = (label, copied) => {
    button.textContent = label;
    if (copied) {
      button.dataset.copied = "true";
    } else {
      delete button.dataset.copied;
    }
  };

  const legacyCopy = (text) => {
    const area = document.createElement("textarea");
    area.className = "copy-fallback";
    area.value = text;
    area.setAttribute("readonly", "");
    document.body.appendChild(area);
    area.select();
    const copied = document.execCommand("copy");
    area.remove();
    return copied;
  };

  button.addEventListener("click", async () => {
    const text = target.textContent.trimEnd();
    let copied = false;

    try {
      await navigator.clipboard.writeText(text);
      copied = true;
    } catch {
      copied = legacyCopy(text);
    }

    setLabel(copied ? "Copied" : "Copy failed", copied);
    window.clearTimeout(resetTimer);
    resetTimer = window.setTimeout(() => setLabel("Copy", false), 2200);
  });
})();
