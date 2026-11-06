// Turkish text and dates. Case and order follow the Turkish locale: "I" lowercases to
// "ı" and "İ" to "i", "Ç" sorts after "C", "Ğ" after "G", "İ" after "I", "Ş" after "S".

export const collator = new Intl.Collator("tr", { numeric: true, sensitivity: "base" });

export const lower = (s) => s.toLocaleLowerCase("tr");
export const upper = (s) => s.toLocaleUpperCase("tr");

// For search only (the text shown is never changed): Turkish lowercase first, so "GELİR"
// is "gelir" (a plain toLowerCase gives "geli̇r", with a combining dot, and "KATMA DEĞER
// VERGİSİ" would not match "vergisi"); then the Turkish letters are folded to their base
// letter, so that a query typed without a Turkish keyboard ("GELIR", "katma deger") finds
// them too.
const BASE = { ı: "i", ğ: "g", ş: "s", ç: "c", ö: "o", ü: "u", â: "a", î: "i", û: "u" };
export const fold = (s) =>
  lower(s).replace(/[ığşçöüâîû]/g, (c) => BASE[c]).replace(/\s+/g, " ").trim();

export const matches = (text, query) => fold(text).includes(fold(query));

const ISO = /^(\d{4})-(\d{2})-(\d{2})$/;
const DMY = /^(\d{1,2})[./](\d{1,2})[./](\d{4})$/;

// "2019-03-15" or "15.03.2019" -> "2019-03-15"; anything else -> null.
export function parseDate(s) {
  if (!s) return null;
  s = s.trim();
  let y, m, d;
  let r = ISO.exec(s);
  if (r) [y, m, d] = [+r[1], +r[2], +r[3]];
  else if ((r = DMY.exec(s))) [d, m, y] = [+r[1], +r[2], +r[3]];
  else return null;
  const t = new Date(Date.UTC(y, m - 1, d));
  if (t.getUTCFullYear() !== y || t.getUTCMonth() !== m - 1 || t.getUTCDate() !== d) return null;
  return `${String(y).padStart(4, "0")}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

// "2019-03-15" -> "15.03.2019"
export function fmtDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  return `${d}.${m}.${y}`;
}

export function today() {
  const t = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${t.getFullYear()}-${p(t.getMonth() + 1)}-${p(t.getDate())}`;
}

// "Madde 41 –" -> "Madde 41"; "Mükerrer Madde 20/A-" -> "Mükerrer Madde 20/A"
export const shortLabel = (label) => label.replace(/\s*\.?\s*[–—-]\s*$/, "");

// "1 madde", "12 madde": Turkish nouns do not take a plural after a number.
export const count = (n, noun) => `${n.toLocaleString("tr-TR")} ${noun}`;
