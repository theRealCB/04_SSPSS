// Barra in alto: pulsante per il menu a sinistra. Indice a destra: freccia dropdown sulla card.
// Lo stato resta salvato nel browser tra una pagina e l'altra.
(function () {
  var NAV_ICON = '<svg viewBox="0 0 24 24" width="24" height="24"><path d="M3 6h18v2H3V6m0 5h18v2H3v-2m0 5h18v2H3v-2Z"/></svg>';
  var CHEVRON = '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M7.41 8.58 12 13.17l4.59-4.59L18 10l-6 6-6-6 1.41-1.42Z"/></svg>';

  function get(key) { try { return localStorage.getItem("sspss-hide-" + key) === "1"; } catch (e) { return false; } }
  function set(key, v) { try { localStorage.setItem("sspss-hide-" + key, v ? "1" : "0"); } catch (e) {} }

  function applyNav(hidden, btn) {
    document.body.classList.toggle("sspss-hide-nav", hidden);
    btn.setAttribute("aria-pressed", hidden ? "false" : "true");
    btn.title = (hidden ? "Mostra" : "Nascondi") + " menu";
    btn.setAttribute("aria-label", btn.title);
  }

  function initNav(header) {
    var sidebar = document.querySelector(".md-sidebar--primary");
    if (!sidebar || sidebar.hidden || !sidebar.querySelector(".md-nav__link")) return;
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "md-header__button md-icon sspss-toggle sspss-toggle--nav";
    btn.innerHTML = NAV_ICON;
    btn.addEventListener("click", function () {
      var hidden = !document.body.classList.contains("sspss-hide-nav");
      set("nav", hidden); applyNav(hidden, btn);
    });
    applyNav(get("nav"), btn);
    header.insertBefore(btn, header.querySelector(".md-header__title"));
  }

  function applyToc(hidden, btn) {
    document.body.classList.toggle("sspss-hide-toc", hidden);
    btn.setAttribute("aria-expanded", hidden ? "false" : "true");
    btn.title = (hidden ? "Mostra" : "Nascondi") + " indice";
    btn.setAttribute("aria-label", btn.title);
  }

  function initToc() {
    var title = document.querySelector(".md-sidebar--secondary .md-nav--secondary > .md-nav__title");
    if (!title || !document.querySelector(".md-sidebar--secondary .md-nav__link")) return;
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "sspss-toc-arrow";
    btn.innerHTML = CHEVRON;
    title.appendChild(btn);
    title.classList.add("sspss-toc-title");
    title.addEventListener("click", function (e) {
      e.preventDefault();
      var hidden = !document.body.classList.contains("sspss-hide-toc");
      set("toc", hidden); applyToc(hidden, btn);
    });
    applyToc(get("toc"), btn);
  }

  function init() {
    var header = document.querySelector(".md-header__inner");
    if (header) initNav(header);
    initToc();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
