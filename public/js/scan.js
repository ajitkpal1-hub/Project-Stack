// RELOOP page helper (progressive enhancement; every page works without it).
// 1. When a photo is taken or chosen, start the scan straight away.
// 2. While a slow form is working (scan, assistant, donate, search), show a loading card.
document.documentElement.classList.add("js");

var LOADING = {
  scan: ["Scanning your photo", ["Uploading your photo…", "Looking at the item…",
    "Checking safety rules and official guidance…", "Still working. This can take up to 15 seconds…"]],
  assistant: ["Finding your answer", ["Searching the official documents…",
    "Writing your answer with sources…", "Still working. This can take up to 15 seconds…"]],
  donate: ["Sending your listing", ["Uploading your listing…", "Still working…"]],
  condition: ["Updating the advice", ["Working out the best option…"]],
  search: ["Searching nearby places", ["Checking our verified directory…",
    "Checking the map. This can take a few seconds…"]]
};

var overlay = null, stepTimer = null, showTimer = null;

function buildOverlay() {
  overlay = document.createElement("div");
  overlay.className = "loading";
  overlay.setAttribute("role", "status");
  overlay.setAttribute("aria-live", "polite");
  overlay.hidden = true;
  var card = document.createElement("div");
  card.className = "loading-card";
  var spinner = document.createElement("span");
  spinner.className = "loading-spinner";
  spinner.setAttribute("aria-hidden", "true");
  var title = document.createElement("p");
  title.className = "loading-title";
  var step = document.createElement("p");
  step.className = "loading-step";
  card.appendChild(spinner); card.appendChild(title); card.appendChild(step);
  overlay.appendChild(card);
  document.body.appendChild(overlay);
}

function showLoading(kind) {
  var entry = LOADING[kind];
  if (!entry) return;
  if (!overlay) buildOverlay();
  var steps = entry[1], i = 0;
  overlay.querySelector(".loading-title").textContent = entry[0];
  overlay.querySelector(".loading-step").textContent = steps[0];
  clearTimeout(showTimer); clearInterval(stepTimer);
  // Only for waits longer than a moment, so quick pages don't flicker.
  showTimer = setTimeout(function () {
    overlay.hidden = false;
    document.body.classList.add("is-loading");
  }, 250);
  stepTimer = setInterval(function () {
    if (i < steps.length - 1) { i += 1; overlay.querySelector(".loading-step").textContent = steps[i]; }
  }, 3000);
}

function hideLoading() {
  clearTimeout(showTimer); clearInterval(stepTimer);
  if (overlay) overlay.hidden = true;
  document.body.classList.remove("is-loading");
  document.querySelectorAll("form.is-busy").forEach(function (f) { f.classList.remove("is-busy"); });
}

document.addEventListener("DOMContentLoaded", function () {
  // Photo pickers: start the scan as soon as a photo is chosen.
  document.querySelectorAll("form.chute").forEach(function (form) {
    var inputs = form.querySelectorAll("input[type=file]");
    inputs.forEach(function (input) {
      input.addEventListener("change", function () {
        if (!input.files || !input.files.length) return;
        inputs.forEach(function (other) { if (other !== input) other.value = ""; });  // send one photo only
        form.classList.add("is-ready");
        if (form.hasAttribute("data-autosubmit")) {
          if (form.requestSubmit) form.requestSubmit(); else { form.classList.add("is-busy"); showLoading("scan"); form.submit(); }
        }
      });
    });
  });

  // Any form marked data-loading shows the loading card while it works, and can't be sent twice.
  document.querySelectorAll("form[data-loading]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (form.classList.contains("is-busy")) { event.preventDefault(); return; }
      form.classList.add("is-busy");
      showLoading(form.getAttribute("data-loading"));
    });
  });
});

// Coming back with the browser's Back button: clear the loading state.
window.addEventListener("pageshow", hideLoading);
