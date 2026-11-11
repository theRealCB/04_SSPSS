// Interfaccia del sito: mega menu Materie, indice a sinistra, card Materiali,
// barra di progresso lettura e statistiche GoatCounter.
(function () {
  var GOATCOUNTER = "appunti-sspss";  // codice del sito su goatcounter.com
  var CHEVRON = '<svg viewBox="0 0 24 24" width="20" height="20"><path d="M7.41 8.58 12 13.17l4.59-4.59L18 10l-6 6-6-6 1.41-1.42Z"/></svg>';

  function get(key) { try { return localStorage.getItem("sspss-" + key) === "1"; } catch (e) { return false; } }
  function set(key, v) { try { localStorage.setItem("sspss-" + key, v ? "1" : "0"); } catch (e) {} }

  /* --- Logo + titolo riportano alla home --- */
  function initHome() {
    var logo = document.querySelector(".md-header__button.md-logo");
    var title = document.querySelector(".md-header__title");
    if (!logo || !title) return;
    title.style.cursor = "pointer";
    title.setAttribute("role", "link");
    title.addEventListener("click", function () { location.href = logo.href; });
  }

  /* --- Mega menu Materie --- */
  function initMega() {
    var header = document.querySelector(".md-header__inner");
    var panel = document.getElementById("sspss-mega");
    if (!header || !panel) return;
    panel.removeAttribute("hidden");
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "sspss-menu-btn";
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-controls", "sspss-mega");
    btn.innerHTML = "Materie " + CHEVRON;
    header.insertBefore(btn, document.querySelector(".md-header__option") || null);

    // Evidenzia la materia della pagina corrente
    var here = decodeURIComponent(location.pathname);
    panel.querySelectorAll(".sspss-mega__item").forEach(function (a) {
      var p = decodeURIComponent(new URL(a.href).pathname);
      if (here.indexOf(p) === 0) a.classList.add("sspss-mega__item--here");
    });

    function open(v) {
      if (v) {
        var r = document.querySelector(".md-header").getBoundingClientRect();
        panel.style.top = (r.bottom + 8) + "px";
      }
      panel.classList.toggle("open", v);
      btn.classList.toggle("open", v);
      btn.setAttribute("aria-expanded", v ? "true" : "false");
    }
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      open(!panel.classList.contains("open"));
    });
    document.addEventListener("click", function (e) {
      if (panel.classList.contains("open") && !panel.contains(e.target)) open(false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") open(false);
    });
  }

  /* --- Indice a sinistra: etichetta --- */
  function initToc() {
    var title = document.querySelector(".md-sidebar--secondary .md-nav--secondary > .md-nav__title");
    if (title) title.textContent = "In questa pagina";
  }

  /* --- Materiali: dal fondo pagina a card richiudibile a destra --- */
  function initMaterials() {
    var src = document.querySelector(".md-content .sspss-materials");
    if (!src) return;
    if (!window.matchMedia("(min-width: 60em)").matches) return;  // su mobile resta in pagina
    var inner = document.querySelector(".md-main__inner");
    if (!inner) return;
    var rail = document.createElement("aside");
    rail.className = "sspss-right";
    var card = document.createElement("div");
    card.className = "sspss-card";
    var head = src.querySelector(".sspss-materials__title");
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "sspss-arrow";
    btn.innerHTML = CHEVRON;
    head.appendChild(btn);
    head.classList.add("sspss-card__head");
    card.appendChild(src);
    rail.appendChild(card);
    inner.appendChild(rail);

    function apply(hidden) {
      document.body.classList.toggle("sspss-hide-mat", hidden);
      btn.setAttribute("aria-expanded", hidden ? "false" : "true");
      btn.title = (hidden ? "Mostra" : "Nascondi") + " materiali";
      btn.setAttribute("aria-label", btn.title);
    }
    head.addEventListener("click", function () {
      var hidden = !document.body.classList.contains("sspss-hide-mat");
      set("hide-mat", hidden); apply(hidden);
    });
    apply(get("hide-mat"));
  }

  /* --- Barra di progresso lettura --- */
  function initProgress() {
    if (!document.querySelector(".md-content")) return;
    var bar = document.createElement("div");
    bar.id = "sspss-progress";
    document.body.appendChild(bar);
    var ticking = false;
    function update() {
      var h = document.documentElement;
      var max = h.scrollHeight - h.clientHeight;
      bar.style.width = (max > 0 ? (h.scrollTop / max) * 100 : 0) + "%";
      ticking = false;
    }
    addEventListener("scroll", function () {
      if (!ticking) { ticking = true; requestAnimationFrame(update); }
    }, { passive: true });
    update();
  }

  /* --- GoatCounter: conteggio visite + visite per materia + ordinamento --- */
  function gcBase() { return "https://" + GOATCOUNTER + ".goatcounter.com"; }

  function initCount() {
    if (!GOATCOUNTER || location.hostname === "localhost" || location.hostname === "127.0.0.1") return;
    var sc = document.createElement("script");
    sc.async = true;
    sc.dataset.goatcounter = gcBase() + "/count";
    sc.src = "https://gc.zgo.at/count.js";
    document.head.appendChild(sc);
  }

  /* Conteggi: TOTAL decide se GoatCounter è attivo; i percorsi 404 valgono 0 */
  function gcFetch(path) {
    return fetch(gcBase() + "/counter/" + encodeURIComponent(path) + ".json")
      .then(function (r) {
        if (r.status === 404) return { miss: true };
        if (!r.ok) return null;
        return r.json();
      })
      .catch(function () { return null; });
  }
  function gcCount(path) {
    // GoatCounter normalizza senza slash finale; prova le varianti in ordine
    var tries = [path.replace(/\/$/, ""), path, decodeURIComponent(path).replace(/\/$/, ""), decodeURIComponent(path)]
      .filter(function (v, i, a) { return a.indexOf(v) === i; });
    var sawMiss = false;
    function next(i) {
      if (i >= tries.length) return Promise.resolve(sawMiss ? 0 : null);
      return gcFetch(tries[i]).then(function (d) {
        if (d && !d.miss) return parseInt(String(d.count).replace(/\D/g, ""), 10) || 0;
        if (d && d.miss) sawMiss = true;
        return next(i + 1);
      });
    }
    return next(0);
  }

  function siteRoot() {
    var logo = document.querySelector(".md-header__button.md-logo");
    return logo ? logo.href : location.href;
  }

  function initStats() {
    if (!GOATCOUNTER) return;
    initSwitch();
    // Prima il file statico aggiornato dalla CI (stesso dominio: passa anche con gli ad-blocker)
    fetch(new URL("assets/stats.json", siteRoot()))
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; })
      .then(function (st) {
        if (st && st.total != null) {
          renderTotal(st.total);
          initCardViews(function (path) {
            var key = decodeURIComponent(path);
            return Promise.resolve(st.paths && key in st.paths ? st.paths[key] : null);
          });
        } else {
          // Fallback: chiamate live a GoatCounter
          gcFetch("TOTAL").then(function (d) {
            if (!d || d.miss) return;
            renderTotal(parseInt(String(d.count).replace(/\D/g, ""), 10) || 0);
            initCardViews(gcCount);
          });
        }
      });
  }

  function renderTotal(n) {
    var chip = document.querySelector(".sspss-stat--visits");
    if (!chip) return;
    chip.querySelector("b").textContent = n.toLocaleString("it-CH");
    chip.hidden = false;
  }

  function initCardViews(counter) {
    var grid = document.querySelector(".grid.cards > ul");
    if (!grid) return;
    [].slice.call(grid.children).forEach(function (li) {
      var a = li.querySelector("p:last-child a");
      var span = li.querySelector(".sspss-views");
      if (!a || !span) return;
      counter(new URL(a.href).pathname).then(function (n) {
        if (n == null) return;
        li.dataset.views = n;
        span.textContent = n.toLocaleString("it-CH") + (n === 1 ? " visita" : " visite");
        span.hidden = false;
      });
    });
  }

  function initSwitch() {
    var sw = document.querySelector(".sspss-switch");
    var grid = document.querySelector(".grid.cards > ul");
    if (!sw || !grid) return;
    var lis = [].slice.call(grid.children);
    lis.forEach(function (li, i) { li.dataset.az = i; });
    sw.addEventListener("click", function () {
      var by = sw.dataset.active === "az" ? "views" : "az";
      sw.dataset.active = by;
      sw.querySelectorAll("button").forEach(function (b) {
        b.setAttribute("aria-pressed", b.dataset.sort === by ? "true" : "false");
      });
      [].slice.call(grid.children)
        .sort(function (x, y) {
          return by === "views"
            ? (+(y.dataset.views || 0)) - (+(x.dataset.views || 0))
            : (+x.dataset.az) - (+y.dataset.az);
        })
        .forEach(function (li) { grid.appendChild(li); });
    });
  }

  function init() {
    initHome(); initMega(); initToc(); initMaterials(); initProgress();
    initCount(); initStats();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
