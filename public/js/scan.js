// RELOOP scan helper (progressive enhancement; every page works without it).
// When a photo is taken or chosen, start the scan straight away and show a "Scanning" state.
document.documentElement.classList.add("js");
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("form.chute").forEach(function (form) {
    var inputs = form.querySelectorAll("input[type=file]");
    inputs.forEach(function (input) {
      input.addEventListener("change", function () {
        if (!input.files || !input.files.length) return;
        inputs.forEach(function (other) { if (other !== input) other.value = ""; });  // send one photo only
        form.classList.add("is-ready");
        if (form.hasAttribute("data-autosubmit")) {
          form.classList.add("is-busy");
          if (form.requestSubmit) form.requestSubmit(); else form.submit();
        }
      });
    });
    form.addEventListener("submit", function () { form.classList.add("is-busy"); });
  });
  // Coming back with the browser's Back button: clear the busy state.
  window.addEventListener("pageshow", function () {
    document.querySelectorAll("form.chute.is-busy").forEach(function (f) { f.classList.remove("is-busy"); });
  });
});
