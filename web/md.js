function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function inline(s) {
  return escapeHtml(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function isSepRow(line) {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
}

function splitCells(line) {
  let t = line.trim();
  if (t.startsWith("|")) t = t.slice(1);
  if (t.endsWith("|")) t = t.slice(0, -1);
  return t.split("|").map((c) => inline(c.trim()));
}

export function looksLikeMarkdown(src) {
  const s = String(src || "");
  return /(?:^|\n)#{1,3} |\*\*[^*]+\*\*|^\s*\|.+\|\s*$|^>\s|^\s*---\s*$|^\s*[-*] |```mermaid/m.test(s);
}

export function renderMarkdown(src) {
  const lines = String(src || "").replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^```mermaid\s*$/.test(line.trim())) {
      i += 1;
      const bits = [];
      while (i < lines.length && !/^```/.test(lines[i].trim())) {
        bits.push(lines[i]);
        i += 1;
      }
      if (i < lines.length) i += 1;
      out.push(`<pre class="mermaid">${escapeHtml(bits.join("\n"))}</pre>`);
      continue;
    }
    if (/^\s*---\s*$/.test(line)) {
      out.push("<hr/>");
      i += 1;
      continue;
    }
    const hm = /^(#{1,3})\s+(.+)$/.exec(line);
    if (hm) {
      const n = hm[1].length;
      out.push(`<h${n}>${inline(hm[2])}</h${n}>`);
      i += 1;
      continue;
    }
    if (line.trim().startsWith("|") && i + 1 < lines.length && isSepRow(lines[i + 1])) {
      const heads = splitCells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith("|") && !isSepRow(lines[i])) {
        rows.push(splitCells(lines[i]));
        i += 1;
      }
      const th = heads.map((c) => `<th>${c}</th>`).join("");
      const tr = rows
        .map((cells) => `<tr>${cells.map((c) => `<td>${c}</td>`).join("")}</tr>`)
        .join("");
      out.push(`<div class="md-table"><table><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`);
      continue;
    }
    if (/^>\s?/.test(line)) {
      const bits = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        bits.push(inline(lines[i].replace(/^>\s?/, "")));
        i += 1;
      }
      out.push(`<blockquote>${bits.join("<br/>")}</blockquote>`);
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const bits = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        bits.push(`<li>${inline(lines[i].replace(/^\s*[-*]\s+/, ""))}</li>`);
        i += 1;
      }
      out.push(`<ul>${bits.join("")}</ul>`);
      continue;
    }
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const bits = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
        bits.push(`<li>${inline(lines[i].replace(/^\s*\d+[.)]\s+/, ""))}</li>`);
        i += 1;
      }
      out.push(`<ol>${bits.join("")}</ol>`);
      continue;
    }
    if (!line.trim()) {
      i += 1;
      continue;
    }
    const para = [inline(line)];
    i += 1;
    while (i < lines.length && lines[i].trim() && !/^(#{1,3}\s|[-*]\s|\d+[.)]\s|>\s|\|)/.test(lines[i]) && !/^\s*---\s*$/.test(lines[i])) {
      para.push(inline(lines[i]));
      i += 1;
    }
    out.push(`<p>${para.join("<br/>")}</p>`);
  }
  return out.join("");
}
