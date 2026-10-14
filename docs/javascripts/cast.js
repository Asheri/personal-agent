// Mount the asciinema player on the homepage.
//
// The full transcript is written out below the player in the Example section,
// so nothing here is load-bearing: if the script fails to load, or the reader
// has JavaScript off, they still get the session.
//
// Material's palette toggle rewrites data-md-color-scheme on <body> without
// reloading, and the player picks its colors once at construction. So watch
// the attribute and rebuild when it changes; otherwise a reader who toggles to
// light is left with a dark terminal and no way to fix it.
(function () {
  var players = new Map();

  function themeFor(scheme) {
    // tango and asciinema supply the ANSI colors; home.css overrides the
    // background and body text so the player sits on the site's code surface.
    return scheme === "slate" ? "asciinema" : "tango";
  }

  function mount(el) {
    if (typeof AsciinemaPlayer === "undefined") {
      return;
    }
    var previous = players.get(el);
    if (previous && typeof previous.dispose === "function") {
      previous.dispose();
    }
    el.innerHTML = "";
    var reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
    var autoPlay = el.dataset.autoplay === "true" && !reduceMotion;
    el.classList.toggle("srag-cast--autoplaying", autoPlay);
    var player = AsciinemaPlayer.create(el.dataset.cast, el, {
      autoPlay: autoPlay,
      loop: autoPlay,
      // The recommended Quick session loops as a picture frame. Advanced and
      // reduced-motion sessions keep controls and wait for the reader.
      controls: !autoPlay,
      preload: true,
      // Hold authored pauses after commands and choices; do not compress them.
      idleTimeLimit: 4,
      speed: 1,
      // Width-fit shrinks the glyphs below the static console next to it.
      // 0.88em is the same rule as `.md-typeset code` in typography.css.
      fit: false,
      terminalFontSize: "0.88em",
      terminalLineHeight: 1.55,
      theme: themeFor(document.body.getAttribute("data-md-color-scheme")),
      terminalFontFamily: "var(--md-code-font-family, monospace)",
    });
    players.set(el, player);
  }

  function mountAll() {
    var elements = document.querySelectorAll(".srag-cast");
    elements.forEach(mount);
  }

  function init() {
    if (!document.querySelectorAll(".srag-cast").length) {
      return;
    }
    mountAll();
    if (init.watching) {
      return;
    }
    init.watching = true;
    new MutationObserver(function () {
      mountAll();
    }).observe(document.body, {
      attributes: true,
      attributeFilter: ["data-md-color-scheme"],
    });
  }

  // extra_javascript can run after DOMContentLoaded, and Material instant
  // navigation never fires that event again. Mount in both cases.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
  if (typeof document$ !== "undefined" && document$.subscribe) {
    document$.subscribe(init);
  }
})();
