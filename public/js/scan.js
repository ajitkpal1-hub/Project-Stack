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

// Phone cameras save 4-12 MB photos, but uploads over ~4.5 MB are refused by the host.
// Shrink the photo on the phone first: a 1600 px JPEG is sharp enough and uploads fast.
var MAX_SIDE = 1600, MAX_BYTES = 4 * 1024 * 1024;

function shrinkInto(input) {
  var file = input.files && input.files[0];
  if (!file || !window.createImageBitmap || !window.DataTransfer) return Promise.resolve(file);
  return createImageBitmap(file, { imageOrientation: "from-image" }).then(function (bitmap) {
    var scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    if (scale === 1 && file.size < 1024 * 1024 && file.type === "image/jpeg") return file;  // already small
    var canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    return new Promise(function (resolve) {
      canvas.toBlob(function (blob) {
        if (!blob) { resolve(file); return; }
        var small = new File([blob], "photo.jpg", { type: "image/jpeg" });
        var list = new DataTransfer(); list.items.add(small); input.files = list.files;
        resolve(small);
      }, "image/jpeg", 0.85);
    });
  }).catch(function () { return file; });  // can't read it here (e.g. HEIC): send as is
}

function photoError(form, message) {
  var box = form.querySelector(".photo-error");
  if (!box) {
    box = document.createElement("p");
    box.className = "notice notice--error photo-error";
    box.setAttribute("role", "alert");
    form.insertBefore(box, form.firstChild);
  }
  box.textContent = message;
}

var TOO_BIG = "That photo is too large to send. Please try again, or choose a smaller photo.";

document.addEventListener("DOMContentLoaded", function () {
  // Photo pickers: shrink the photo, then start the scan straight away.
  document.querySelectorAll("form.chute").forEach(function (form) {
    var inputs = form.querySelectorAll("input[type=file]");
    inputs.forEach(function (input) {
      input.addEventListener("change", function () {
        if (!input.files || !input.files.length) return;
        inputs.forEach(function (other) { if (other !== input) other.value = ""; });  // send one photo only
        form.classList.add("is-ready");
        if (!form.hasAttribute("data-autosubmit")) { shrinkInto(input); return; }
        form.classList.add("is-busy");
        showLoading("scan");
        shrinkInto(input).then(function (file) {
          if (file && file.size > MAX_BYTES) { hideLoading(); input.value = ""; photoError(form, TOO_BIG); return; }
          form.submit();  // the loading card is already showing
        });
      });
    });
  });

  // Other photo fields (donation photo): shrink as soon as one is chosen.
  document.querySelectorAll("input[type=file][data-shrink]").forEach(function (input) {
    input.addEventListener("change", function () {
      shrinkInto(input).then(function (file) {
        if (file && file.size > MAX_BYTES) { input.value = ""; photoError(input.form, TOO_BIG); }
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
