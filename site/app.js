/* Builds the field guide from the repository itself.
   Source of truth for which use cases exist: the use-case table in README.md.
   site/cases.json adds plain-language plates; rows it does not know yet are
   described from their own README so new cases appear without editing the site. */
(() => {
  "use strict";

  const FALLBACK_REPO = "https://github.com/marioaguileraaa/sre-agent-use-cases";
  const keyEl = document.querySelector("[data-key]");
  const thumbsEl = document.querySelector("[data-thumbs]");
  const platesEl = document.querySelector("[data-plates]");
  const iconOut = document.getElementById("icon-out");

  const repoUrl = (() => {
    const host = location.hostname;
    const first = location.pathname.split("/").filter(Boolean)[0];
    if (host.endsWith(".github.io") && first) return `https://github.com/${host.split(".")[0]}/${first}`;
    return FALLBACK_REPO;
  })();

  document.querySelectorAll("[data-repo]").forEach((a) => { a.href = repoUrl; });

  const el = (tag, attrs = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "style") node.style.cssText = v;
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const child of children.flat(Infinity)) {
      if (child === undefined || child === null || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  };
  const icon = () => iconOut.content.firstElementChild.cloneNode(true);
  const svg = (paths, cls) => {
    const node = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    node.setAttribute("viewBox", "0 0 24 24");
    node.setAttribute("aria-hidden", "true");
    node.setAttribute("class", cls);
    node.innerHTML = paths;
    return node;
  };
  let player = null;

  const stripMd = (s) => s
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[*_`]/g, "")
    .replace(/\s+/g, " ")
    .trim();

  const sentence = (s, max) => {
    const clean = stripMd(s).replace(/\s*Business value( and limits)?\.?$/i, "");
    if (clean.length <= max) return clean;
    const cut = clean.slice(0, max);
    const stop = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("; "));
    return (stop > max * 0.5 ? cut.slice(0, stop + 1) : cut.replace(/\s+\S*$/, "") + "…").trim();
  };

  const parseTable = (md) => {
    const rows = [];
    const re = /^\|\s*(\d{2,3})\s*\|\s*\[\*\*(.+?)\*\*[^\]]*\]\(([^)\s]+)\)[^|]*\|(.*?)\|(.*?)\|\s*$/;
    for (const line of md.split(/\r?\n/)) {
      const m = line.match(re);
      if (!m) continue;
      rows.push({ no: m[1], title: stripMd(m[2]), folder: m[3].replace(/^\.\//, "").replace(/\/$/, ""), what: m[4].trim(), blocks: m[5].trim() });
    }
    return rows;
  };

  const cronToWords = (cron) => {
    const p = cron.trim().split(/\s+/);
    if (p.length !== 5) return null;
    const [, , dom, , dow] = p;
    const days = ["Sundays", "Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays"];
    if (dom !== "*" && /^\d+$/.test(dom)) {
      const n = Number(dom);
      const suffix = n % 10 === 1 && n !== 11 ? "st" : n % 10 === 2 && n !== 12 ? "nd" : n % 10 === 3 && n !== 13 ? "rd" : "th";
      return `Monthly, on the ${n}${suffix}`;
    }
    if (dow !== "*" && /^\d$/.test(dow)) return `Weekly, on ${days[Number(dow)]}`;
    if (dom === "*" && dow === "*") return "Daily";
    return null;
  };

  const famStyle = (f) => `--fam:${f.fill};--fam-ink:${f.ink};--on-fam:${f.on}`;

  async function getJson(url) {
    const r = await fetch(url, { cache: "no-cache" });
    if (!r.ok) throw new Error(`${url}: ${r.status}`);
    return r.json();
  }
  async function getText(url) {
    const r = await fetch(url, { cache: "no-cache" });
    if (!r.ok) throw new Error(`${url}: ${r.status}`);
    return r.text();
  }

  function mergeCases(curated, rows) {
    const known = curated.cases;
    if (!rows.length) {
      return Object.entries(known).map(([folder, c]) => ({ ...c, folder, no: folder.match(/^\d+/)?.[0] ?? "00", curated: true }));
    }
    return rows.map((r) => {
      const c = known[r.folder];
      if (c) return { ...c, folder: r.folder, no: r.no, curated: true };
      return {
        folder: r.folder,
        no: r.no,
        family: "new",
        name: r.title,
        key: sentence(r.title, 70),
        symptom: null,
        does: sentence(r.what, 320),
        runs: null,
        reads: null,
        delivers: null,
        curated: false,
      };
    });
  }

  function renderKey(families, cases) {
    keyEl.replaceChildren();
    for (const f of families) {
      const items = cases.filter((c) => c.family === f.id);
      if (!items.length) continue;
      const group = el("section", { class: "key-group", style: famStyle(f), "aria-label": f.name },
        el("h3", {}, f.name),
        el("ul", { class: "key-list" }, items.map((c) =>
          el("li", {},
            el("a", { class: "entry", href: `#plate-${c.no}`, "data-entry": c.folder },
              el("img", { src: c.thumb || c.image || "site/img/plates/blank.svg", alt: "", width: 60, height: 38, loading: "eager", decoding: "async" }),
              el("span", { class: "entry-text" }, c.key),
              el("span", { class: "entry-no" }, el("span", { class: "vh" }, "Plate "), c.no)))))
      );
      keyEl.append(group);
    }
  }

  function renderThumbs(families, cases) {
    thumbsEl.replaceChildren();
    const present = families.filter((f) => cases.some((c) => c.family === f.id));
    thumbsEl.style.setProperty("--n", present.length);
    present.forEach((f, i) => {
      thumbsEl.append(el("a", { class: "tab", href: `#family-${f.id}`, style: `${famStyle(f)};--i:${i}`, "data-tab": f.id }, el("span", {}, f.short)));
    });
  }

  function plate(c, f, byFolder) {
    const guideUrl = `${repoUrl}/tree/main/${c.folder}`;
    const compareWith = (c.compare || []).map((k) => byFolder.get(k)).filter(Boolean);
    const marks = [
      ["Runs", c.runs],
      ["Reads", c.reads],
      ["Changes", c.changes || "Nothing. Read-only"],
      ["Delivers", c.delivers],
    ].filter(([, v]) => v);

    const fullHref = c.full || c.image;
    const fullLabel = c.full && c.full.endsWith(".html") ? "Open the sample report" : "View full size";

    const figure = el("figure", { class: `plate-fig${c.illustration ? " illustration" : ""}` },
      el("a", { class: "plate-frame", href: fullHref || guideUrl, rel: "noopener", "aria-label": `${fullLabel}: ${c.name}` },
        c.image
          ? el("img", { src: c.image, alt: c.illustration ? "Cartoon of a smiling engineer in a blue hard hat and overalls, holding a glowing wrench and a floating cloud dashboard with a green check mark." : `Report produced by the ${c.name} use case.`, width: c.illustration ? 1000 : 1200, height: c.illustration ? 1001 : 750, loading: "lazy", decoding: "async" })
          : el("span", { class: "plate-pending" }, "Screenshots are in the guide on GitHub")),
      el("figcaption", {},
        el("b", {}, `Plate ${c.no}. `),
        c.caption || "From the guide on GitHub.",
        c.full ? el("a", { href: fullHref, rel: "noopener" }, fullLabel) : null));

    const text = el("div", { class: "plate-text" },
      el("div", { class: "plate-head" },
        el("p", { class: "plate-no", "aria-hidden": "true" }, c.no),
        el("h3", { id: `plate-${c.no}-title` }, el("span", { class: "vh" }, `Use case ${c.no}: `), c.name),
        c.latin ? el("p", { class: "latin" }, el("span", { class: "vh" }, "Subagent: "), c.latin) : el("p", { class: "latin", "data-latin": "" })),
      c.symptom ? el("p", { class: "symptom" }, c.symptom) : null,
      el("p", { class: "does" }, el("b", {}, "What the agent does. "), c.does),
      el("dl", { class: "marks", "data-marks": "" },
        marks.map(([k, v]) => el("div", {}, el("dt", {}, k), el("dd", {}, v))),
        compareWith.length ? el("div", { class: "compare" }, el("dt", {}, "Compare with"),
          el("dd", {}, compareWith.map((o, i) => [i ? ", " : "", el("a", { href: `#plate-${o.no}` }, `No. ${o.no} ${o.name}`)]))) : null),
      el("a", { class: "guide", href: guideUrl, rel: "noopener" }, "Open the step-by-step guide", icon()),
      c.tutorial ? tutorialCard(c) : null);

    return el("article", { class: "plate", id: `plate-${c.no}`, "aria-labelledby": `plate-${c.no}-title`, "data-folder": c.folder, style: famStyle(f) }, text, figure);
  }

  function tutorialCard(c) {
    const t = c.tutorial;
    const card = el("button", { class: "tutorial", type: "button", "aria-haspopup": "dialog", "data-tutorial": "" },
      el("span", { class: "tutorial-thumb" },
        el("img", { src: t.thumb || t.poster, alt: "", width: 208, height: 117, loading: "lazy", decoding: "async" }),
        el("span", { class: "tutorial-play" }, svg('<path d="M8.5 5.8v12.4c0 .6.7 1 1.2.6l9.3-6.2c.5-.3.5-1 0-1.3L9.7 5.2c-.5-.4-1.2 0-1.2.6z"/>', "play")),
        el("span", { class: "tutorial-time" }, el("span", { class: "vh" }, "Length "), t.duration)),
      el("span", { class: "tutorial-text" },
        el("b", {}, "Watch the tutorial"),
        el("span", {}, t.teaser)));
    card.addEventListener("click", () => openPlayer(c, card));
    return card;
  }

  function buildPlayer(c) {
    const t = c.tutorial;
    const video = el("video", { controls: true, playsinline: true, muted: true, preload: "none", poster: t.poster, width: 1920, height: 1080 },
      el("source", { src: t.video, type: "video/mp4" }));
    video.muted = true;
    const close = el("button", { class: "player-close", type: "button", "aria-label": "Close the tutorial" },
      svg('<path d="M6 6l12 12M18 6 6 18"/>', "icon"));
    const dlg = el("dialog", { class: "player", "aria-labelledby": "player-title" },
      el("div", { class: "player-head" },
        el("h2", { id: "player-title" }, t.title),
        close),
      el("div", { class: "player-screen" }, video),
      el("p", { class: "player-foot" },
        `Plate ${c.no}, ${c.name.toLowerCase()} · ${t.duration} · no voice-over, every step is captioned on screen · `,
        el("a", { href: t.video, download: "" }, "Download the video"),
        " · ",
        el("a", { href: `${repoUrl}/tree/main/${c.folder}`, rel: "noopener" }, "Step-by-step guide")));
    close.addEventListener("click", () => dlg.close());
    dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
    dlg.addEventListener("close", () => {
      video.pause();
      if (location.hash === "#tutorial") history.replaceState(null, "", location.pathname + location.search);
    });
    document.body.append(dlg);
    return { dlg, video };
  }

  function openPlayer(c, opener) {
    if (!player) player = buildPlayer(c);
    if (player.dlg.open) return;
    player.dlg.showModal();
    player.opener = opener;
    const p = player.video.play();
    if (p && p.catch) p.catch(() => {});
  }

  function renderPlates(families, cases) {
    platesEl.replaceChildren();
    const byFolder = new Map(cases.map((c) => [c.folder, c]));
    for (const f of families) {
      const items = cases.filter((c) => c.family === f.id);
      if (!items.length) continue;
      platesEl.append(el("section", { class: "family", id: `family-${f.id}`, "data-family": f.id, style: famStyle(f), "aria-labelledby": `family-${f.id}-title` },
        el("header", { class: "family-head" },
          el("h2", { id: `family-${f.id}-title` }, f.name),
          el("p", {}, f.about)),
        items.map((c) => plate(c, f, byFolder))));
    }
  }

  // Describe a case the curated file does not know yet from its own README.
  async function enrich(c) {
    let md;
    try { md = await getText(`${c.folder}/README.md`); } catch { return; }
    const node = platesEl.querySelector(`[data-folder="${CSS.escape(c.folder)}"]`);
    if (!node) return;
    const img = md.match(/!\[([^\]]*)\]\(([^)\s]+)\)/);
    if (img && !/^https?:/i.test(img[2])) {
      const src = `${c.folder}/${img[2].replace(/^\.\//, "")}`;
      const frame = node.querySelector(".plate-frame");
      frame.href = src;
      frame.replaceChildren(el("img", { src, alt: stripMd(img[1]) || `Screenshot from the ${c.name} guide.`, loading: "lazy", decoding: "async" }));
      const entryImg = keyEl.querySelector(`[data-entry="${CSS.escape(c.folder)}"] img`);
      if (entryImg) entryImg.src = src;
    }
    const agents = [...md.matchAll(/@([a-z][a-z0-9-]{4,})/g)].map((m) => m[1]).filter((a) => !/^(odata|azure|contoso)/.test(a));
    if (agents.length) {
      const top = Object.entries(agents.reduce((acc, a) => ((acc[a] = (acc[a] || 0) + 1), acc), {})).sort((a, b) => b[1] - a[1])[0][0];
      const latin = node.querySelector("[data-latin]");
      if (latin) latin.replaceChildren(el("span", { class: "vh" }, "Subagent: "), top);
    }
    const cron = md.match(/`(\d{1,2} \d{1,2} [\d*]+ \* [\d*]+)`/);
    const runs = cron && cronToWords(cron[1]);
    if (runs) {
      const marks = node.querySelector("[data-marks]");
      marks.prepend(el("div", {}, el("dt", {}, "Runs"), el("dd", {}, runs)));
    }
  }

  function trackFamilies() {
    const tabs = new Map([...thumbsEl.querySelectorAll("[data-tab]")].map((t) => [t.dataset.tab, t]));
    let current = null;
    const set = (id) => {
      if (id === current) return;
      current = id;
      tabs.forEach((t, k) => t.setAttribute("aria-current", String(k === id)));
      const tab = tabs.get(id);
      // On narrow screens the tabs are a horizontal strip: keep the active one in view.
      if (tab && thumbsEl.scrollWidth > thumbsEl.clientWidth) {
        const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
        thumbsEl.scrollTo({ left: Math.max(0, tab.offsetLeft - 24), behavior: reduce ? "auto" : "smooth" });
      }
    };
    const sections = [...platesEl.querySelectorAll("[data-family]")];
    if (!("IntersectionObserver" in window) || !sections.length) return;
    const visible = new Map();
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) visible.set(e.target.dataset.family, e.isIntersecting ? e.intersectionRect.height : 0);
      let best = null, max = 0;
      visible.forEach((h, k) => { if (h > max) { max = h; best = k; } });
      if (best) set(best);
      else { current = null; tabs.forEach((t) => t.setAttribute("aria-current", "false")); }
    }, { threshold: [0, 0.1, 0.25, 0.5, 0.75, 1], rootMargin: "-20% 0px -40% 0px" });
    sections.forEach((s) => io.observe(s));
  }

  function showError() {
    keyEl.replaceChildren(el("p", { class: "load-error" }, "The list of use cases could not be loaded right now. ",
      el("a", { href: repoUrl }, "Browse them on GitHub"), "."));
  }

  async function main() {
    let curated;
    try { curated = await getJson("site/cases.json"); } catch { showError(); return; }
    let rows = [];
    try { rows = parseTable(await getText("README.md")); } catch { /* use the curated plates only */ }
    const cases = mergeCases(curated, rows);
    const families = curated.families;
    renderKey(families, cases);
    renderThumbs(families, cases);
    renderPlates(families, cases);
    trackFamilies();
    const more = () => thumbsEl.classList.toggle("has-more", thumbsEl.scrollLeft + thumbsEl.clientWidth < thumbsEl.scrollWidth - 2);
    thumbsEl.addEventListener("scroll", more, { passive: true });
    addEventListener("resize", more, { passive: true });
    more();
    cases.filter((c) => !c.curated).forEach(enrich);
    if (location.hash === "#tutorial") {
      const withVideo = cases.find((c) => c.tutorial);
      const card = platesEl.querySelector("[data-tutorial]");
      if (withVideo && card) {
        card.closest(".plate")?.scrollIntoView();
        openPlayer(withVideo, card);
      }
    } else if (location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView();
  }

  main();
})();
