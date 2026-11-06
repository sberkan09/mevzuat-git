// The data written by `mevzuat-git site` (src/mevzuat_git/site.py), and what a date means.
//
// Commits are in publication order and dated by yürürlük, so dates do not always
// increase. The text of an article on day D is its version from the last commit, in
// publication order, dated on or before D. Same rule as `article_at` in site.py.

const cache = new Map();

async function getJSON(path) {
  if (!cache.has(path)) {
    cache.set(path, fetch(path).then((r) => {
      if (!r.ok) throw new Error(`${path}: ${r.status}`);
      return r.json();
    }));
  }
  return cache.get(path);
}

export const loadIndex = () => getJSON("data/index.json");

export async function loadLaw(number) {
  const law = await getJSON(`data/${number}.json`);
  if (!law.slugs) {
    // "mukerrer-20/A" -> "mukerrer-20-A" in URLs.
    law.slugs = new Map(Object.keys(law.articles).map((id) => [slug(id), id]));
  }
  return law;
}

export const slug = (id) => id.replace(/\//g, "-").replace(/~/g, "_");

export const startDate = (law) => law.commits[0].date;

// {version, pending} for an article on ``day`` (ISO string). ``version`` is null before
// the history begins or while the article does not exist. ``pending``: commits whose
// change the version may carry although it was not yet in force on ``day``.
export function articleAt(law, id, day) {
  const versions = law.articles[id].versions;
  let best = -1;
  versions.forEach((v, k) => {
    if (law.commits[v.c].date <= day) best = k;
  });
  if (best < 0) return { version: null, pending: [] };
  const pending = versions.slice(0, best).filter((v) => law.commits[v.c].date > day).map((v) => v.c);
  const v = versions[best];
  return { version: v.absent ? null : v, pending };
}

// The table of contents on ``day``: headings ({l, t, s}) and article ids.
export function tocAt(law, day) {
  let best = null;
  for (const t of law.toc) if (law.commits[t.c].date <= day) best = t;
  return best ? best.items : null;
}

// Text outside articles, if the law has any.
export function preambleAt(law, day) {
  let best = null;
  for (const p of law.preamble) if (law.commits[p.c].date <= day) best = p;
  return best ? best.body : [];
}

// Timeline of an article, in publication order: each version, and each commit that names
// the article without changing its text.
export function timeline(law, id) {
  const versions = law.articles[id].versions;
  const byCommit = new Map(versions.map((v, k) => [v.c, k]));
  const out = [];
  law.commits.forEach((c, i) => {
    if (byCommit.has(i)) {
      const k = byCommit.get(i);
      out.push({ commit: c, index: i, version: versions[k], previous: k > 0 ? versions[k - 1] : null });
    } else if (c.named.includes(id) || (c.failed && c.failed[id])) {
      out.push({ commit: c, index: i, version: null, unchanged: true });
    }
  });
  return out;
}

export const UNKNOWN_TEXT = "[Bu tarihteki metin bilinmiyor.]";

export const hasUnknown = (v) =>
  !!v && ((v.title || "").includes(UNKNOWN_TEXT) ||
    v.body.some((b) => (typeof b === "string" ? b.includes(UNKNOWN_TEXT) : b.some((r) => r.some((c) => c.includes(UNKNOWN_TEXT))))));

// Failed operations on an article, over the whole history: [{commit, lines}].
export function failures(law, id) {
  return law.commits.filter((c) => c.failed && c.failed[id]).map((c) => ({ commit: c, lines: c.failed[id] }));
}
