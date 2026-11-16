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
  /* --- Colonna destra (creata solo quando serve) --- */
  function getRail() {
    var rail = document.querySelector(".sspss-right");
    if (rail) return rail;
    var inner = document.querySelector(".md-main__inner");
    if (!inner) return null;
    rail = document.createElement("aside");
    rail.className = "sspss-right";
    inner.appendChild(rail);
    return rail;
  }
  function wide() { return window.matchMedia("(min-width: 60em)").matches; }

  /* --- Pulsante "Fai il quiz": su desktop sale nella colonna destra --- */
  function initQuizLink() {
    var link = document.querySelector(".md-content a.sspss-quizlink");
    if (!link || !wide()) return;  // su mobile resta accanto al pulsante PDF
    var rail = getRail();
    if (!rail) return;
    link.classList.add("sspss-quizlink--rail");
    rail.appendChild(link);
  }
  function initGlossLink() {
    var link = document.querySelector(".md-content a.sspss-glosslink");
    if (!link || !wide()) return;
    var rail = getRail();
    if (!rail) return;
    link.classList.add("sspss-glosslink--rail");
    rail.appendChild(link);
  }

  function initMaterials() {
    var src = document.querySelector(".md-content .sspss-materials");
    if (!src) return;
    if (!wide()) return;  // su mobile resta in pagina
    var rail = getRail();
    if (!rail) return;
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
    if (document.querySelector(".sspss-hero")) return;  // niente barra in home
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

  /* --- Centro download: checkbox e zip --- */
  function initDownloads() {
    var boxes = [].slice.call(document.querySelectorAll(".sspss-dl-box"));
    var bar = document.querySelector(".sspss-dlbar");
    if (!boxes.length || !bar) return;
    var count = bar.querySelector(".sspss-dlbar__count");
    var go = bar.querySelector(".sspss-dlbar__go");

    function refresh() {
      var sel = boxes.filter(function (b) { return b.checked; });
      go.disabled = !sel.length;
      count.textContent = !sel.length ? "Nessun file selezionato"
        : sel.length === 1 ? "1 file selezionato" : sel.length + " file selezionati";
      document.querySelectorAll(".sspss-dl").forEach(function (sec) {
        var all = sec.querySelector(".sspss-dl-all");
        var own = [].slice.call(sec.querySelectorAll(".sspss-dl-box"));
        var n = own.filter(function (b) { return b.checked; }).length;
        all.checked = n === own.length;
        all.indeterminate = n > 0 && n < own.length;
      });
    }
    boxes.forEach(function (b) { b.addEventListener("change", refresh); });
    document.querySelectorAll(".sspss-dl").forEach(function (sec) {
      sec.querySelector(".sspss-dl-all").addEventListener("change", function () {
        var v = this.checked;
        sec.querySelectorAll(".sspss-dl-box").forEach(function (b) { b.checked = v; });
        refresh();
      });
    });
    refresh();

    function loadJSZip() {
      if (window.JSZip) return Promise.resolve();
      return new Promise(function (ok, no) {
        var sc = document.createElement("script");
        sc.src = new URL("assets/jszip.min.js", siteRoot());
        sc.onload = ok; sc.onerror = no;
        document.head.appendChild(sc);
      });
    }

    go.addEventListener("click", function () {
      var sel = boxes.filter(function (b) { return b.checked; });
      if (!sel.length) return;
      go.disabled = true;
      var done = 0, failed = [];
      loadJSZip().then(function () {
        var zip = new JSZip();
        return Promise.all(sel.map(function (b) {
          return fetch(b.dataset.url)
            .then(function (r) { if (!r.ok) throw 0; return r.blob(); })
            .then(function (blob) { zip.file(b.dataset.zip, blob); })
            .catch(function () { failed.push(b.dataset.zip.split("/").pop()); })
            .then(function () {
              done += 1;
              go.textContent = "Preparo lo zip… " + done + "/" + sel.length;
            });
        })).then(function () {
          go.textContent = "Comprimo…";
          return zip.generateAsync({ type: "blob" });
        }).then(function (blob) {
          var a = document.createElement("a");
          a.href = URL.createObjectURL(blob);
          a.download = "appunti-sspss.zip";
          document.body.appendChild(a); a.click(); a.remove();
          setTimeout(function () { URL.revokeObjectURL(a.href); }, 30000);
          go.textContent = "Scarica lo zip";
          go.disabled = false;
          count.textContent = failed.length
            ? "Zip pronto; " + failed.length + " file non trovati: " + failed.join(", ")
            : "Zip scaricato";
        });
      }).catch(function () {
        go.textContent = "Scarica lo zip";
        go.disabled = false;
        count.textContent = "Errore nel preparare lo zip, riprova";
      });
    });
  }

  /* --- Quiz --- */
  function shuffle(a) {
    a = a.slice();
    for (var i = a.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var t = a[i]; a[i] = a[j]; a[j] = t;
    }
    return a;
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function initQuiz() {
    var box = document.querySelector(".sspss-quiz");
    if (!box) return;
    fetch(box.dataset.src)
      .then(function (r) { if (!r.ok) throw 0; return r.json(); })
      .then(function (all) { run(all); })
      .catch(function () { box.textContent = "Non riesco a caricare il quiz. Ricarica la pagina."; });

    function norm(t) { return String(t).toLowerCase().normalize("NFD").replace(/[^a-z0-9]/g, ""); }

    // Capitoli degli appunti: titolo -> ancora, letti dalla pagina della materia
    var back = box.dataset.back || "../";
    var anchors = fetch(back)
      .then(function (r) { return r.ok ? r.text() : ""; })
      .then(function (html) {
        var map = {};
        var doc = new DOMParser().parseFromString(html, "text/html");
        doc.querySelectorAll(".md-content h1[id], .md-content h2[id], .md-content h3[id], .md-content h4[id], .md-content h5[id]")
          .forEach(function (h) {
            var c = h.cloneNode(true);
            c.querySelectorAll(".headerlink").forEach(function (x) { x.remove(); });
            var k = norm(c.textContent);
            if (!(k in map)) map[k] = h.id;
          });
        return map;
      })
      .catch(function () { return {}; });

    function run(all) {
      var qs = shuffle(all), i = 0, log = [];
      function score() { return log.filter(function (a) { return a.ok; }).length; }

      function question() {
        box.innerHTML = "";
        var q = qs[i];
        var head = el("div", "sspss-quiz__head");
        head.appendChild(el("span", "sspss-quiz__count", "Domanda " + (i + 1) + " di " + qs.length));
        var stop = el("button", "sspss-quiz__stop", "Termina ora");
        stop.type = "button";
        stop.addEventListener("click", result);
        head.appendChild(stop);
        box.appendChild(head);
        var bar = el("div", "sspss-quiz__bar");
        var fill = el("span");
        fill.style.width = (i / qs.length * 100) + "%";
        bar.appendChild(fill);
        box.appendChild(bar);
        box.appendChild(el("p", "sspss-quiz__q", q.q));

        var opts = el("div", "sspss-quiz__opts");
        var after = el("div", "sspss-quiz__after");
        shuffle([q.correct].concat(q.wrong)).forEach(function (text) {
          var b = el("button", "sspss-quiz__opt", text);
          b.type = "button";
          b.addEventListener("click", function () {
            var ok = text === q.correct;
            log.push({ cap: q.cap || "", ok: ok });
            [].forEach.call(opts.children, function (o) {
              o.disabled = true;
              if (o.textContent === q.correct) o.classList.add("is-right");
            });
            if (!ok) b.classList.add("is-wrong");
            after.appendChild(el("p", "sspss-quiz__verdict " + (ok ? "is-right" : "is-wrong"),
              ok ? "Giusto." : "Non proprio."));
            if (q.why) after.appendChild(el("p", "sspss-quiz__why", q.why));
            var next = el("button", "md-button sspss-quiz__next",
              i + 1 < qs.length ? "Avanti" : "Vedi il risultato");
            next.type = "button";
            next.addEventListener("click", function () { i += 1; i < qs.length ? question() : result(); });
            after.appendChild(next);
            next.focus();
          });
          opts.appendChild(b);
        });
        box.appendChild(opts);
        box.appendChild(after);
      }

      function result() {
        box.innerHTML = "";
        var done = log.length, right = score();
        var row = el("div", "sspss-quiz__row");
        var again = el("button", "md-button", done ? "Riprova" : "Ricomincia");
        again.type = "button";
        again.addEventListener("click", function () { run(all); });
        var home = el("a", "sspss-quiz__back", "Torna agli appunti");
        home.href = back;
        row.appendChild(again); row.appendChild(home);

        if (!done) {
          box.appendChild(el("p", "sspss-quiz__msg", "Non hai risposto a nessuna domanda, quindi non c'è niente da valutare."));
          box.appendChild(row);
          return;
        }
        var pct = Math.round(right / done * 100);
        box.appendChild(el("p", "sspss-quiz__final", right + " / " + done));
        if (done < qs.length) {
          box.appendChild(el("p", "sspss-quiz__partial",
            "Hai terminato prima: valutazione su " + done + " domande delle " + qs.length + " disponibili."));
        }

        // Analisi per capitolo
        var caps = {}, order = [];
        log.forEach(function (a) {
          if (!caps[a.cap]) { caps[a.cap] = { ok: 0, ko: 0 }; order.push(a.cap); }
          caps[a.cap][a.ok ? "ok" : "ko"] += 1;
        });
        var weak = order.filter(function (c) { return caps[c].ko > 0; })
          .sort(function (x, y) { return caps[y].ko - caps[x].ko; });
        var strong = order.filter(function (c) { return caps[c].ko === 0; });

        var msg;
        if (!weak.length) msg = "Tutte giuste: su questi argomenti sei solido.";
        else if (pct >= 80) msg = "Buon risultato. Gli errori sono concentrati in " +
          (weak.length === 1 ? "un solo capitolo" : weak.length + " capitoli") + ": basta un ripasso mirato.";
        else if (pct >= 50) msg = "Base discreta, ma " + (weak.length === 1 ? "un capitolo va rivisto" : weak.length + " capitoli vanno rivisti") + " prima di sentirti sicuro.";
        else msg = "C'è ancora da lavorare: conviene rileggere i capitoli qui sotto e poi riprovare.";
        if (weak.length && strong.length) {
          msg += " Vanno bene invece " + strong.length + (strong.length === 1 ? " capitolo" : " capitoli") + " su " + order.length + ".";
        }
        box.appendChild(el("p", "sspss-quiz__msg", msg));

        if (weak.length) {
          box.appendChild(el("p", "sspss-quiz__label", "Da ripassare"));
          var ul = el("ul", "sspss-quiz__review");
          weak.forEach(function (c) {
            var li = el("li");
            var a = el("a", null, c || "Appunti");
            a.href = back;
            li.appendChild(a);
            var n = caps[c].ko, tot = caps[c].ko + caps[c].ok;
            li.appendChild(el("span", null, n + (n === 1 ? " errore" : " errori") + " su " + tot));
            ul.appendChild(li);
            anchors.then(function (map) {
              var id = map[norm(c)];
              if (id) a.href = back + "#" + id;
            });
          });
          box.appendChild(ul);
        }
        box.appendChild(row);
      }

      question();
    }
  }

  /* --- Ingrandimento delle immagini al clic --- */
  function initZoom() {
    var imgs = document.querySelectorAll(".md-content img");
    if (!imgs.length) return;
    var layer = null;
    function close() { if (layer) { layer.remove(); layer = null; } }
    function open(img) {
      close();
      layer = el("div", "sspss-lightbox");
      var big = document.createElement("img");
      big.src = img.currentSrc || img.src;
      big.alt = img.alt || "";
      layer.appendChild(big);
      layer.addEventListener("click", close);
      document.body.appendChild(layer);
    }
    [].forEach.call(imgs, function (img) {
      if (img.closest("a")) return;
      img.classList.add("sspss-zoomable");
      img.addEventListener("click", function () { open(img); });
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });
  }

  function init() {
    initHome(); initMega(); initToc(); initQuizLink(); initGlossLink(); initMaterials(); initProgress();
    initCount(); initStats(); initDownloads(); initQuiz(); initZoom();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
