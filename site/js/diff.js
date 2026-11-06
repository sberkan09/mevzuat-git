// Inline diff of two article texts: paragraphs are matched first (LCS), then each changed
// paragraph is compared word by word with the one that replaced it.
//
// diffBlocks(a, b) -> [{type: "eq"|"del"|"ins", text} | {type: "mod", parts: [{type, text}]}]

const MAX_CELLS = 4_000_000; // beyond this, a changed paragraph shows as removed + added

// Table rows as text lines, so a table diffs like a paragraph.
export const blockText = (b) => (typeof b === "string" ? b : b.map((r) => r.join(" | ")).join("\n"));

// Longest common subsequence of two arrays: the pairs (i, j) of equal items, in order.
function lcs(a, b, eq = (x, y) => x === y) {
  const n = a.length, m = b.length;
  // Common prefix and suffix need no table.
  let s = 0;
  while (s < n && s < m && eq(a[s], b[s])) s++;
  let e = 0;
  while (e < n - s && e < m - s && eq(a[n - 1 - e], b[m - 1 - e])) e++;
  const pairs = [];
  for (let k = 0; k < s; k++) pairs.push([k, k]);
  const an = n - s - e, bm = m - s - e;
  if (an > 0 && bm > 0) {
    if ((an + 1) * (bm + 1) > MAX_CELLS) return null;
    const w = bm + 1;
    const t = new Uint32Array((an + 1) * w);
    for (let i = an - 1; i >= 0; i--) {
      for (let j = bm - 1; j >= 0; j--) {
        t[i * w + j] = eq(a[s + i], b[s + j])
          ? t[(i + 1) * w + j + 1] + 1
          : Math.max(t[(i + 1) * w + j], t[i * w + j + 1]);
      }
    }
    let i = 0, j = 0;
    while (i < an && j < bm) {
      if (eq(a[s + i], b[s + j])) { pairs.push([s + i, s + j]); i++; j++; }
      else if (t[(i + 1) * w + j] >= t[i * w + j + 1]) i++;
      else j++;
    }
  }
  for (let k = 0; k < e; k++) pairs.push([n - e + k, m - e + k]);
  return pairs;
}

// Words and the spaces between them, so that joining the tokens gives back the text.
const tokens = (s) => s.match(/\s+|[^\s]+/g) || [];

export function diffWords(a, b) {
  const x = tokens(a), y = tokens(b);
  const pairs = lcs(x, y);
  if (pairs === null) return [{ type: "del", text: a }, { type: "ins", text: b }];
  const out = [];
  const push = (type, text) => {
    if (!text) return;
    const last = out[out.length - 1];
    if (last && last.type === type) last.text += text;
    else out.push({ type, text });
  };
  let i = 0, j = 0;
  for (const [pi, pj] of [...pairs, [x.length, y.length]]) {
    push("del", x.slice(i, pi).join(""));
    push("ins", y.slice(j, pj).join(""));
    if (pi < x.length) push("eq", x[pi]);
    i = pi + 1; j = pj + 1;
  }
  // Changes separated only by spaces read as one: "eski1 eski2" -> "yeni1 yeni2", not
  // four interleaved pieces.
  const merged = [];
  for (let k = 0; k < out.length; k++) {
    const p = out[k];
    if (p.type === "eq") { merged.push(p); continue; }
    let del = "", ins = "";
    let q = k;
    for (;;) {
      while (q < out.length && out[q].type !== "eq") {
        if (out[q].type === "del") del += out[q].text; else ins += out[q].text;
        q++;
      }
      if (q + 1 < out.length && /^\s+$/.test(out[q].text) && out[q + 1].type !== "eq") {
        del += out[q].text; ins += out[q].text; q++;
      } else break;
    }
    if (del) merged.push({ type: "del", text: del });
    if (ins) merged.push({ type: "ins", text: ins });
    k = q - 1;
  }
  return merged;
}

// Share of a paragraph's words that the other keeps: below this, they are different
// paragraphs (one removed, one added), not one paragraph changed.
const SIMILAR = 0.3;

function similarity(a, b) {
  const x = tokens(a).filter((t) => /\S/.test(t)), y = tokens(b).filter((t) => /\S/.test(t));
  if (!x.length || !y.length) return 0;
  const pairs = lcs(x, y);
  if (pairs === null) return 0;
  return (2 * pairs.length) / (x.length + y.length);
}

export function diffBlocks(aBlocks, bBlocks) {
  const a = aBlocks.map(blockText), b = bBlocks.map(blockText);
  const pairs = lcs(a, b) || [];
  const out = [];
  let i = 0, j = 0;
  for (const [pi, pj] of [...pairs, [a.length, b.length]]) {
    const dels = a.slice(i, pi), inss = b.slice(j, pj);
    // Pair removed and added paragraphs in order while they look alike.
    let d = 0, k = 0;
    while (d < dels.length || k < inss.length) {
      if (d < dels.length && k < inss.length && similarity(dels[d], inss[k]) >= SIMILAR) {
        out.push({ type: "mod", parts: diffWords(dels[d], inss[k]) });
        d++; k++;
      } else if (d < dels.length && (k >= inss.length || dels.length - d >= inss.length - k)) {
        out.push({ type: "del", text: dels[d++] });
      } else {
        out.push({ type: "ins", text: inss[k++] });
      }
    }
    if (pi < a.length) out.push({ type: "eq", text: a[pi] });
    i = pi + 1; j = pj + 1;
  }
  return out;
}

export const changed = (ops) => ops.some((o) => o.type !== "eq");
