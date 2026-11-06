// The viewer: hash routes, so that every view is a link that works on a static host.
//
//   #/                                kanun listesi
//   #/193?tarih=2019-03-15            kanunun o tarihteki metni ve içindekiler
//   #/193/41?tarih=2019-03-15         madde: o tarihteki metin, zaman çizelgesi
//   #/193/41?tarih=2010-01-01&ile=2019-03-15   madde: iki tarih arası fark
//   #/193/fark?tarih=2010-01-01&ile=2019-03-15  kanun: iki tarih arası fark
//
// Text from the data is always set as text (never as HTML).

import {
  articleAt, hasUnknown, loadIndex, loadLaw, preambleAt, slug, startDate, timeline, tocAt,
} from "./data.js";
import { changed, diffBlocks } from "./diff.js";
import { collator, count, fmtDate, matches, parseDate, shortLabel, today } from "./tr.js";

const main = document.getElementById("main");

// -- DOM helpers ---------------------------------------------------------------------------

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const link = (href, ...children) => h("a", { href }, ...children);
const ext = (href, ...children) => h("a", { href, target: "_blank", rel: "noopener" }, ...children);

// -- routes --------------------------------------------------------------------------------

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const params = new URLSearchParams(query);
  return { parts, params };
}

function href(law, art, params = {}) {
  let p = "#/";
  if (law) p += law;
  if (art) p += "/" + art;
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) q.set(k, v);
  const s = q.toString();
  return s ? `${p}?${s}` : p;
}

function go(to, replace = false) {
  if (replace) history.replaceState(null, "", to);
  else history.pushState(null, "", to);
  render();
}

let index = null;
let rendered = null; // the route on screen: hashchange and popstate both fire on "back"

async function render() {
  if (location.hash === rendered) return;
  rendered = location.hash;
  const { parts, params } = parseHash();
  try {
    index = index || (await loadIndex());
    if (parts.length === 0) return showIndex(params);
    const number = parts[0];
    const meta = index.laws.find((l) => String(l.number) === number);
    if (!meta) return notFound(`${number} sayılı kanun bu sitede yok.`);
    const law = await loadLaw(number);
    if (parts.length === 1) return showLaw(law, meta, params);
    if (parts[1] === "fark") return showLawDiff(law, meta, params);
    const id = law.slugs.get(parts[1]);
    if (!id) return notFound(`${number} sayılı Kanunda "${parts[1]}" diye bir madde bulunamadı.`);
    return showArticle(law, meta, id, params);
  } catch (e) {
    console.error(e);
    setMain(h("div", { class: "notice error" }, "Veri yüklenemedi: ", e.message));
  }
}

function setMain(...children) {
  main.replaceChildren(...children.flat().filter((c) => c !== null && c !== undefined && c !== false));
  window.scrollTo(0, 0);
}

function notFound(msg) {
  document.title = "Bulunamadı · Mevzuat Tarihçesi";
  setMain(h("div", { class: "notice error" }, msg, " ", link("#/", "Kanun listesine dön")));
}

// The date a view asks for: ?tarih=, or today. A date in the URL may be 15.03.2019 too.
function dayParam(params, key = "tarih") {
  return parseDate(params.get(key) || "");
}

// -- kanun listesi -------------------------------------------------------------------------

function showIndex(params) {
  document.title = "Kanunlar · Mevzuat Tarihçesi";
  const q = params.get("ara") || "";
  const order = params.get("sira") === "ad" ? "ad" : "no";
  const list = h("ul", { class: "laws" });
  const fill = () => {
    const query = search.value;
    const laws = index.laws
      .filter((l) => !query || matches(`${l.number} ${l.name}`, query))
      .sort((a, b) => (sort.value === "ad" ? collator.compare(a.name, b.name) : a.number - b.number));
    list.replaceChildren(...laws.map((l) => h("li", {},
      link(href(l.number), h("span", { class: "law-no" }, `${l.number} sayılı`), " ", h("span", { class: "law-name" }, l.name)),
      h("div", { class: "law-meta" },
        `${fmtDate(l.first)} – ${fmtDate(l.last)} · ${count(l.commits, "değişiklik")} · ${count(l.articles, "madde")}`,
        l.unverified ? h("span", { class: "badge unverified" }, `${l.unverified} madde doğrulanmadı`) : null),
    )));
    if (!laws.length) list.append(h("li", { class: "empty" }, `"${query}" için sonuç yok.`));
    const p = { ara: query, sira: sort.value === "ad" ? "ad" : "" };
    history.replaceState(null, "", href(null, null, p));
    rendered = location.hash;
  };
  const search = h("input", { type: "search", name: "ara", placeholder: "Kanun ara: numara ya da ad", value: q, "aria-label": "Kanun ara", oninput: fill });
  const sort = h("select", { name: "sira", "aria-label": "Sıralama", onchange: fill },
    h("option", { value: "no" }, "Numaraya göre"), h("option", { value: "ad" }, "Ada göre"));
  sort.value = order;
  setMain(
    h("h1", {}, "Kanunlar"),
    h("p", { class: "lead" },
      "Her kanunun Resmî Gazete'de yayımlanan değişikliklerle geçirdiği hâller, yürürlük tarihleriyle. ",
      "Bir tarih seçerek kanunun o günkü metnini, bir maddeye girerek değişiklik geçmişini görebilirsiniz."),
    h("div", { class: "toolbar" }, search, sort),
    list,
  );
  fill();
}

// -- shared pieces -------------------------------------------------------------------------

function lawHeader(law, meta, crumbs = []) {
  return h("nav", { class: "crumbs", "aria-label": "Konum" },
    link("#/", "Kanunlar"), " › ",
    crumbs.length ? link(href(law.number), `${law.number} sayılı ${law.name}`) : `${law.number} sayılı ${law.name}`,
    crumbs.flatMap((c) => [" › ", c]));
}

function dateForm({ day, other, onSubmit, compare = false, law }) {
  const input = h("input", { type: "date", name: "tarih", value: day || "", min: startDate(law), required: true, "aria-label": "Tarih" });
  const input2 = compare ? h("input", { type: "date", name: "ile", value: other || "", min: startDate(law), "aria-label": "Karşılaştırılacak tarih" }) : null;
  const form = h("form", {
    class: "dateform",
    onsubmit: (e) => {
      e.preventDefault();
      onSubmit(input.value, input2 ? input2.value : null);
    },
  },
  h("label", {}, compare ? "Tarih: " : "Bu tarihteki metin: ", input),
  compare ? h("label", {}, " ile ", input2) : null,
  h("button", { type: "submit" }, compare ? "Karşılaştır" : "Göster"));
  input.addEventListener("change", () => { if (input.value && !compare) form.requestSubmit(); });
  return form;
}

const STATUS = {
  verified: ["Doğrulandı", "Değişikliklerin yeniden uygulanmasıyla elde edilen son metin, mevzuat.gov.tr'deki güncel konsolide metinle birebir aynı."],
  typography: ["Yazım farkı", "Yeniden uygulama sonucu güncel metinle içerikçe aynı; yalnız tırnak, tire, şapka gibi yazım farkları var. Ara sürümlerin yazımı değiştiren kanunun yazımıdır."],
  unverified: ["Doğrulanmadı", "Değişikliklerin yeniden uygulanması bu maddenin güncel metnini üretemedi (Resmî Gazete metni okunamayan ya da ayrıştırılamayan değişiklikler). Güncel metin resmî konsolide metindir, ama önceki tarihlerin metinleri eksik ya da hatalı olabilir; bu metinlere güvenmeyin."],
};

function statusBadge(status, long = false) {
  const [label, help] = STATUS[status];
  const badge = h("span", { class: `badge ${status}`, title: help }, label);
  if (!long) return badge;
  return h("div", { class: `status-box ${status}`, role: status === "unverified" ? "alert" : null }, badge, " ", help);
}

function blocks(body) {
  return body.map((b) => (typeof b === "string"
    ? h("p", {}, b)
    : h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, b[0].map((c) => h("th", {}, c)))),
      h("tbody", {}, b.slice(1).map((r) => h("tr", {}, r.map((c) => h("td", {}, c)))))))));
}

function commitLine(law, c) {
  const rg = c.rg_date ? `RG ${fmtDate(c.rg_date)}${c.rg_number ? `, sayı ${c.rg_number}` : ""}` : null;
  return [
    h("strong", {}, actName(c)),
    rg ? ` · ${rg}` : "",
    ` · yürürlük ${fmtDate(c.date)}`,
    c.assumed ? h("span", { class: "badge warn", title: "Yürürlük tablosunda bu değişikliğin satırı bulunamadı; yayım tarihi varsayıldı." }, "tarih varsayıldı") : null,
  ];
}

function actName(c) {
  if (c.kind === "start") return "Başlangıç metni";
  if (c.kind === "sync") return "Güncel metinle eşitleme";
  if (c.kind === "aym") return c.act.replace(/^AYM /, "Anayasa Mahkemesi ");
  return c.act;
}

function commitLinks(c) {
  return h("span", { class: "links" },
    c.source ? ext(c.source, "Resmî Gazete") : null,
    c.source && index.source.url ? " · " : null,
    index.source.url ? ext(`${index.source.url}/commit/${c.sha}`, "commit") : null);
}

function versionNotes(law, id, version, pending) {
  const out = [];
  const c = law.commits[version.c];
  if (c.kind === "sync") {
    out.push(h("div", { class: "notice warn" },
      "Bu metin, tarihçenin sonundaki güncel metinle eşitleme adımından geliyor: değişikliklerin yeniden uygulanması bu metni üretemedi. ",
      "Metnin hangi kanunla ve hangi tarihte bu hâle geldiği bilinmiyor; gösterilen tarih (", fmtDate(c.date), ") tarihçenin son tarihidir."));
  }
  if (hasUnknown(version)) {
    out.push(h("div", { class: "notice warn" },
      "Bu sürümde \"[Bu tarihteki metin bilinmiyor.]\" yazan kısımların o tarihteki metni elde değil: sonradan bütünüyle değiştirildikleri için eski hâlleri bulunamadı."));
  }
  if (c.failed && c.failed[id]) {
    out.push(h("div", { class: "notice warn" },
      `${actName(c)} ile gelen bazı işlemler bu maddeye uygulanamadı; metin eksik olabilir.`,
      h("ul", { class: "mono" }, c.failed[id].map((l) => h("li", {}, l)))));
  }
  if (pending.length) {
    out.push(h("div", { class: "notice warn" },
      "Bu metin, seçilen tarihte henüz yürürlükte olmayan şu değişiklikleri de içeriyor olabilir (daha önce yayımlanıp daha geç yürürlüğe girdiler): ",
      h("ul", {}, pending.map((i) => h("li", {}, commitLine(law, law.commits[i]))))));
  }
  if (c.source_note) out.push(h("div", { class: "notice info" }, `Kaynak notu: ${c.source_note}.`));
  return out;
}

function beforeHistory(law, day) {
  return h("div", { class: "notice warn" },
    `${fmtDate(day)} tarihli metin elde yok. Bu kanunun tarihçesi ${fmtDate(startDate(law))} tarihinde, Resmî Gazete metni elde olan en eski değişiklikten önceki hâliyle başlıyor. `,
    link(href(law.number, null, { tarih: startDate(law) }), "En eski metne git"));
}

function copyLinkButton() {
  const b = h("button", {
    type: "button", class: "secondary",
    onclick: async () => {
      try { await navigator.clipboard.writeText(location.href); b.textContent = "Bağlantı kopyalandı"; }
      catch { b.textContent = "Kopyalanamadı: adres çubuğundaki bağlantıyı kullanın"; }
      setTimeout(() => { b.textContent = "Bağlantıyı kopyala"; }, 2500);
    },
  }, "Bağlantıyı kopyala");
  return b;
}

// -- kanun sayfası -------------------------------------------------------------------------

function showLaw(law, meta, params) {
  const day = dayParam(params) || today();
  document.title = `${law.number} sayılı ${law.name} (${fmtDate(day)}) · Mevzuat Tarihçesi`;
  const toc = tocAt(law, day);
  const form = dateForm({ law, day, onSubmit: (d) => go(href(law.number, null, { tarih: d })) });
  const tools = h("div", { class: "toolbar" }, form,
    link(href(law.number, "fark", { tarih: startDate(law), ile: day }), "İki tarihi karşılaştır"),
    copyLinkButton());
  const head = [lawHeader(law, meta), h("h1", {}, `${law.number} sayılı ${law.name}`),
    h("p", { class: "lead" }, `${fmtDate(day)} tarihindeki metin. `,
      `Tarihçe: ${fmtDate(law.first)} – ${fmtDate(law.last)}, ${count(law.commits.length, "adım")}.`),
    tools];
  if (!toc) return setMain(...head, beforeHistory(law, day));

  const filter = h("input", { type: "search", placeholder: "Madde ara: numara ya da başlık", "aria-label": "Madde ara" });
  const tocList = h("ol", { class: "toc" });
  const text = h("div", { class: "law-text" });
  const unverifiedHere = [];
  text.append(...blocks(preambleAt(law, day)));
  for (const item of toc) {
    if (typeof item !== "string") {
      const tag = item.l === 2 ? "h2" : "h3";
      text.append(h(tag, { class: "law-heading" }, item.t, item.s ? h("span", { class: "sub" }, item.s) : null));
      tocList.append(h("li", { class: `toc-h l${item.l}`, "data-text": `${item.t} ${item.s || ""}` }, item.t, item.s ? ` – ${item.s}` : ""));
      continue;
    }
    const a = law.articles[item];
    const { version, pending } = articleAt(law, item, day);
    if (!version) continue;
    const label = shortLabel(version.label);
    const s = slug(item);
    if (a.status === "unverified") unverifiedHere.push(label);
    tocList.append(h("li", { class: "toc-a", "data-text": `${label} ${version.title}` },
      link(`#m-${s}`, label), version.title ? ` ${version.title}` : "",
      a.status !== "verified" ? [" ", statusBadge(a.status)] : null));
    text.append(h("article", { class: `article ${a.status}`, id: `m-${s}` },
      h("h4", {}, link(href(law.number, s, { tarih: day }), label),
        version.title ? ` ${version.title}` : "", " ", statusBadge(a.status),
        pending.length ? h("span", { class: "badge warn", title: "Bu tarihte henüz yürürlükte olmayan bir değişikliği içeriyor olabilir." }, "yürürlük sırası") : null,
        hasUnknown(version) ? h("span", { class: "badge warn" }, "metin kısmen bilinmiyor") : null),
      blocks(version.body),
      h("p", { class: "article-tools" }, link(href(law.number, s, { tarih: day }), "Bu maddenin geçmişi ve farkları →"))));
  }
  filter.addEventListener("input", () => {
    for (const li of tocList.children) li.hidden = !!filter.value && !matches(li.dataset.text, filter.value);
  });
  // A click in the table of contents scrolls; the hash route stays as it is.
  tocList.addEventListener("click", (e) => {
    const a = e.target.closest("a");
    if (!a) return;
    e.preventDefault();
    document.getElementById(a.getAttribute("href").slice(1))?.scrollIntoView();
  });
  const summary = unverifiedHere.length
    ? h("div", { class: "status-box unverified", role: "note" }, statusBadge("unverified"), " ",
      `Bu kanunun ${count(unverifiedHere.length, "maddesi")} doğrulanmadı: ${unverifiedHere.join(", ")}. `,
      "Bu maddelerin önceki tarihlerdeki metinleri eksik ya da hatalı olabilir.")
    : null;
  const order = law.order_differs
    ? h("div", { class: "notice warn" }, "Maddelerin sırası, yeniden uygulama sonucunda güncel metindekinden farklı çıktı; sıralama doğrulanmadı.")
    : null;
  setMain(...head, summary, order,
    h("div", { class: "law-layout" },
      h("details", { class: "toc-box", open: window.matchMedia("(min-width: 900px)").matches },
        h("summary", {}, "İçindekiler"), filter, tocList),
      text));
}

// -- madde sayfası -------------------------------------------------------------------------

function showArticle(law, meta, id, params) {
  const a = law.articles[id];
  const s = slug(id);
  const day = dayParam(params) || today();
  const other = dayParam(params, "ile");
  const label = shortLabel(a.label);
  document.title = `${law.number} sayılı Kanun ${label} (${fmtDate(day)}) · Mevzuat Tarihçesi`;
  const { version, pending } = articleAt(law, id, day);
  const head = [
    lawHeader(law, meta, [label]),
    h("h1", {}, label, a.title ? h("span", { class: "sub" }, a.title) : null),
    statusBadge(a.status, true),
  ];
  const form = dateForm({ law, day, onSubmit: (d) => go(href(law.number, s, { tarih: d, ile: other })) });
  const cmp = dateForm({
    law, day, other: other || "", compare: true,
    onSubmit: (d1, d2) => go(href(law.number, s, { tarih: d1, ile: d2 })),
  });

  const current = h("section", { class: "current", "aria-labelledby": "current-h" });
  current.append(h("h2", { id: "current-h" }, `${fmtDate(day)} tarihindeki metin`));
  if (day < startDate(law)) current.append(beforeHistory(law, day));
  else if (!version) current.append(h("div", { class: "notice info" }, "Bu madde bu tarihte kanunda yoktu (henüz eklenmemişti ya da kaldırılmıştı)."));
  else {
    const c = law.commits[version.c];
    current.append(
      h("p", { class: "from" }, "Bu metin: ", commitLine(law, c), " ", commitLinks(c)),
      ...versionNotes(law, id, version, pending),
      h("div", { class: "article-body", "data-testid": "article-text" },
        version.title !== a.title || version.label !== a.label
          ? h("p", { class: "version-title" }, shortLabel(version.label), " ", version.title) : null,
        blocks(version.body)),
    );
  }

  let diffSection = null;
  if (other) {
    const x = articleAt(law, id, day).version, y = articleAt(law, id, other).version;
    diffSection = h("section", { class: "diff-section", "aria-labelledby": "diff-h" },
      h("h2", { id: "diff-h" }, `${fmtDate(day)} → ${fmtDate(other)} farkı`),
      diffView(x, y));
  }

  setMain(...head,
    h("div", { class: "toolbar" }, form, copyLinkButton()),
    current,
    h("details", { class: "compare", open: !!other }, h("summary", {}, "İki tarih arasındaki farkı göster"), cmp),
    diffSection,
    timelineView(law, id, version));
}

// Inline diff of two versions (either may be null: the article did not exist).
function diffView(x, y) {
  const xb = x ? x.body : [], yb = y ? y.body : [];
  const ops = diffBlocks(
    x ? [`${shortLabel(x.label)} ${x.title}`.trim(), ...xb] : [],
    y ? [`${shortLabel(y.label)} ${y.title}`.trim(), ...yb] : []);
  if (!changed(ops)) return h("p", { class: "notice info" }, "İki tarih arasında bu maddenin metni değişmemiş.");
  const out = h("div", { class: "diff", "data-testid": "diff" });
  // Unchanged paragraphs far from a change are folded.
  const near = ops.map((o, k) => o.type !== "eq" || (ops[k - 1] && ops[k - 1].type !== "eq") || (ops[k + 1] && ops[k + 1].type !== "eq"));
  let folded = 0;
  const flush = () => {
    if (folded) out.append(h("p", { class: "fold" }, `… değişmeyen ${count(folded, "paragraf")} …`));
    folded = 0;
  };
  ops.forEach((o, k) => {
    if (o.type === "eq" && !near[k]) { folded++; return; }
    flush();
    if (o.type === "eq") out.append(h("p", {}, o.text));
    else if (o.type === "del") out.append(h("p", { class: "del" }, h("del", {}, o.text)));
    else if (o.type === "ins") out.append(h("p", { class: "ins" }, h("ins", {}, o.text)));
    else out.append(h("p", { class: "mod" }, o.parts.map((p) => (p.type === "eq" ? p.text : h(p.type, {}, p.text)))));
  });
  flush();
  return out;
}

function timelineView(law, id, shown) {
  const s = slug(id);
  const items = timeline(law, id);
  const list = h("ol", { class: "timeline" });
  for (const it of items) {
    const c = it.commit;
    const isShown = shown && it.version === shown;
    const li = h("li", { class: `tl-item ${c.kind}${isShown ? " shown" : ""}${it.unchanged ? " unchanged" : ""}` },
      h("div", { class: "tl-date" }, fmtDate(c.date)),
      h("div", { class: "tl-body" },
        h("div", {}, commitLine(law, c), " ", commitLinks(c)),
        c.by ? h("div", { class: "tl-by" }, c.by) : null,
        it.unchanged ? h("div", { class: "tl-note" }, "Bu değişiklik maddeyi anıyor, ama tarihçede madde metni değişmedi (işlem uygulanamadı ya da metne etkisi yok).") : null,
        c.kind === "sync" ? h("div", { class: "tl-note" }, "Yeniden uygulama ile güncel metin arasındaki fark burada kapatıldı; farkın gerçek tarihi bilinmiyor.") : null,
        c.failed && c.failed[id] ? h("div", { class: "tl-note warn" }, `${count(c.failed[id].length, "işlem")} uygulanamadı.`) : null,
        it.version && it.version.absent ? h("div", { class: "tl-note" }, "Madde metinden çıktı.") : null,
        it.version ? h("div", { class: "tl-actions" },
          isShown ? h("span", { class: "badge" }, "gösterilen metin") : link(href(law.number, s, { tarih: c.date }), "Bu tarihteki metin"),
          it.previous ? h("details", {}, h("summary", {}, "Önceki hâliyle farkı"),
            diffView(it.previous.absent ? null : it.previous, it.version.absent ? null : it.version)) : null) : null));
    list.append(li);
  }
  return h("section", { class: "history", "aria-labelledby": "tl-h" },
    h("h2", { id: "tl-h" }, "Değişiklik geçmişi"),
    h("p", { class: "lead" }, "Yayım sırasıyla. Tarih, yürürlük tarihidir; sonra yayımlanan bir değişiklik daha önce yürürlüğe girmiş olabilir."),
    list);
}

// -- iki tarih arası kanun farkı -----------------------------------------------------------

function showLawDiff(law, meta, params) {
  const day = dayParam(params) || startDate(law);
  const other = dayParam(params, "ile") || today();
  document.title = `${law.number} sayılı Kanun: ${fmtDate(day)} → ${fmtDate(other)} · Mevzuat Tarihçesi`;
  const form = dateForm({ law, day, other, compare: true, onSubmit: (a, b) => go(href(law.number, "fark", { tarih: a, ile: b })) });
  const head = [lawHeader(law, meta, ["Karşılaştırma"]),
    h("h1", {}, `${fmtDate(day)} → ${fmtDate(other)}`),
    h("div", { class: "toolbar" }, form, copyLinkButton())];
  const t1 = tocAt(law, day) || [], t2 = tocAt(law, other) || [];
  const ids = [];
  for (const i of [...t1, ...t2]) if (typeof i === "string" && !ids.includes(i)) ids.push(i);
  // Order of the later text, then articles only in the earlier one.
  const order = new Map(t2.filter((i) => typeof i === "string").map((i, k) => [i, k]));
  ids.sort((a, b) => (order.get(a) ?? 1e9) - (order.get(b) ?? 1e9));
  const sections = [];
  for (const id of ids) {
    const x = articleAt(law, id, day).version, y = articleAt(law, id, other).version;
    if (x === y) continue;
    const a = law.articles[id];
    const s = slug(id);
    sections.push(h("article", { class: `article ${a.status}` },
      h("h3", {}, link(href(law.number, s, { tarih: day, ile: other }), shortLabel(a.label)), a.title ? ` ${a.title}` : "", " ", statusBadge(a.status),
        !x ? h("span", { class: "badge info" }, "eklendi") : !y ? h("span", { class: "badge info" }, "çıktı") : null),
      diffView(x, y)));
  }
  const notes = [];
  if (day < startDate(law) || other < startDate(law)) notes.push(beforeHistory(law, day < other ? day : other));
  setMain(...head, ...notes,
    h("p", { class: "lead" }, sections.length ? `${count(sections.length, "maddenin")} metni değişmiş.` : "İki tarih arasında metni değişen madde yok."),
    ...sections);
}

// -- theme ---------------------------------------------------------------------------------

function setupTheme() {
  const btn = document.getElementById("theme");
  const root = document.documentElement;
  let saved = null;
  try { saved = localStorage.getItem("tema"); } catch { /* storage unavailable */ }
  if (saved === "koyu" || saved === "acik") root.dataset.theme = saved === "koyu" ? "dark" : "light";
  const label = () => {
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    btn.textContent = dark ? "Açık tema" : "Koyu tema";
    btn.setAttribute("aria-pressed", String(dark));
    return dark;
  };
  btn.addEventListener("click", () => {
    const dark = !label();
    root.dataset.theme = dark ? "dark" : "light";
    try { localStorage.setItem("tema", dark ? "koyu" : "acik"); } catch { /* ignore */ }
    label();
  });
  label();
}

async function footer() {
  try {
    const idx = await loadIndex();
    const el = document.getElementById("source");
    if (idx.source.url) {
      el.replaceChildren("Veri: ", ext(idx.source.url, idx.source.url.replace("https://github.com/", "")),
        " @ ", ext(`${idx.source.url}/commit/${idx.source.head}`, idx.source.head.slice(0, 7)), ". ");
    }
  } catch { /* the main view reports it */ }
}

window.addEventListener("hashchange", render);
window.addEventListener("popstate", render);
setupTheme();
footer();
render();
