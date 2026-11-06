// Unit tests of the viewer's pure functions: npm run test:unit
import assert from "node:assert/strict";
import { test } from "node:test";

import { articleAt, tocAt } from "../../site/js/data.js";
import { diffBlocks, diffWords } from "../../site/js/diff.js";
import { collator, fmtDate, fold, lower, matches, parseDate, shortLabel, upper } from "../../site/js/tr.js";

const join = (parts, type) => parts.filter((p) => p.type === "eq" || p.type === type).map((p) => p.text).join("");

test("diffWords gives back both texts", () => {
  // GVK md. 40/1, before and after 5035 (verbatim).
  const a = "1. Ticari kazancın elde edilmesi ve idame ettirilmesi için yapılan genel giderler;";
  const b = "1. Ticari kazancın elde edilmesi ve idame ettirilmesi için yapılan genel giderler (Ticari kazancın elde edilmesi ile ilgili olarak yapılan giderler);";
  const parts = diffWords(a, b);
  assert.equal(join(parts, "del"), a);
  assert.equal(join(parts, "ins"), b);
  assert.deepEqual(parts.filter((p) => p.type !== "eq").map((p) => p.type), ["del", "ins"]);
});

test("diffWords merges changes separated by a space", () => {
  const parts = diffWords("yüzde on beş oranında", "yüzde yirmi altı oranında");
  assert.deepEqual(parts, [
    { type: "eq", text: "yüzde " },
    { type: "del", text: "on beş" },
    { type: "ins", text: "yirmi altı" },
    { type: "eq", text: " oranında" },
  ]);
});

test("diffBlocks pairs similar paragraphs and keeps new ones whole", () => {
  const a = ["Aşağıda yazılı ödemelerin gider olarak indirilmesi kabul olunmaz:", "1. Teşebbüs sahibinin işletmeye koyduğu sermaye için yürütülecek faizler;"];
  const b = [...a, "9. Basın yoluyla işlenen fiillerden veya radyo ve televizyon yayınlarından doğacak maddî ve manevî zararlardan dolayı ödenen tazminat giderleri."];
  const ops = diffBlocks(a, b);
  assert.deepEqual(ops.map((o) => o.type), ["eq", "eq", "ins"]);
  const mod = diffBlocks(["2. Kanunî ve iktisadî ölçülere uymayan giderler"], ["2. Kanuni ve iktisadi ölçülere uymayan giderler"]);
  assert.equal(mod[0].type, "mod");
  assert.deepEqual(diffBlocks([], ["x"]).map((o) => o.type), ["ins"]);
  assert.deepEqual(diffBlocks(["x"], []).map((o) => o.type), ["del"]);
});

test("tables diff as text", () => {
  const t1 = [["Gelir dilimi", "Oran"], ["110.000 TL'ye kadar", "15"]];
  const t2 = [["Gelir dilimi", "Oran"], ["158.000 TL'ye kadar", "15"]];
  const ops = diffBlocks([t1], [t2]);
  assert.equal(ops[0].type, "mod");
});

test("Turkish case", () => {
  assert.equal(lower("GELİR VERGİSİ"), "gelir vergisi");
  assert.equal(lower("KATMA DEĞER VERGİSİ KANUNU"), "katma değer vergisi kanunu");
  assert.equal(lower("ISTISNA"), "ıstısna");
  assert.equal(upper("istisna"), "İSTİSNA");
  assert.equal(upper("ılık"), "ILIK");
});

test("search folds Turkish letters only after a Turkish lowercase", () => {
  assert.ok(matches("GELİR VERGİSİ KANUNU (G.V.K.)", "gelir vergisi"));
  assert.ok(matches("GELİR VERGİSİ KANUNU (G.V.K.)", "GELIR"));
  assert.ok(matches("KATMA DEĞER VERGİSİ KANUNU", "katma deger"));
  assert.ok(matches("Gider kabul edilmiyen ödemeler:", "ÖDEMELER"));
  assert.ok(!matches("VERGİ USUL KANUNU", "gelir"));
  assert.equal(fold("  Değer   Vergisi "), "deger vergisi");
});

test("Turkish order", () => {
  const words = ["Şirket", "Çiftçi", "Ücret", "Sermaye", "Cari", "İstisna", "Irat", "Gider", "Ğ", "Zarar", "Ödeme", "Oran"];
  assert.deepEqual([...words].sort(collator.compare),
    ["Cari", "Çiftçi", "Gider", "Ğ", "Irat", "İstisna", "Oran", "Ödeme", "Sermaye", "Şirket", "Ücret", "Zarar"]);
  assert.deepEqual(["Madde 10", "Madde 9", "Madde 100"].sort(collator.compare), ["Madde 9", "Madde 10", "Madde 100"]);
});

test("dates", () => {
  assert.equal(parseDate("15.03.2019"), "2019-03-15");
  assert.equal(parseDate("3/7/2001"), "2001-07-03");
  assert.equal(parseDate("2019-03-15"), "2019-03-15");
  assert.equal(parseDate("31.02.2019"), null);
  assert.equal(parseDate("dün"), null);
  assert.equal(fmtDate("2002-05-21"), "21.05.2002");
  assert.equal(shortLabel("Mükerrer Madde 20/A-"), "Mükerrer Madde 20/A");
  assert.equal(shortLabel("Madde 41 –"), "Madde 41");
});

// The rule of site.py's article_at: last version in publication order dated on or before
// the day; earlier-published versions dated after it are pending.
const law = {
  commits: [
    { date: "2001-07-03" }, { date: "2012-08-29" }, { date: "2012-07-12" }, { date: "2026-08-01" },
  ],
  toc: [{ c: 0, items: ["94"] }, { c: 3, items: ["94", "95"] }],
  articles: {
    94: { versions: [{ c: 0, body: ["a"] }, { c: 1, body: ["b"] }, { c: 2, body: ["c"] }] },
    95: { versions: [{ c: 3, body: ["new"] }] },
  },
};

test("articleAt", () => {
  assert.deepEqual(articleAt(law, "94", "2000-01-01"), { version: null, pending: [] });
  assert.equal(articleAt(law, "94", "2012-01-01").version.body[0], "a");
  const mid = articleAt(law, "94", "2012-08-01");
  assert.equal(mid.version.body[0], "c");
  assert.deepEqual(mid.pending, [1]);
  assert.deepEqual(articleAt(law, "94", "2012-08-29").pending, []);
  assert.equal(articleAt(law, "95", "2020-01-01").version, null);
  assert.deepEqual(tocAt(law, "2020-01-01"), ["94"]);
  assert.deepEqual(tocAt(law, "2026-08-01"), ["94", "95"]);
  assert.equal(tocAt(law, "1990-01-01"), null);
});
