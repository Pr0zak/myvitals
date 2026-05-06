/**
 * Minimal markdown → HTML renderer for Claude-generated summaries.
 * Handles only the subset our system prompt asks for: paragraphs,
 * one ## heading, **bold**, *italic*, simple bullet lists, links.
 * Keeps the bundle out of a markdown dependency for ~50 lines of code.
 *
 * Output is HTML-escaped by default; explicit constructs are then
 * un-escaped to inline tags. We never render code blocks.
 */

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]!));
}

function inlineFmt(line: string): string {
  let s = esc(line);
  // bold **x**
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  // italic *x*
  s = s.replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
  // [text](url)
  s = s.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    (_m, text: string, url: string) =>
      `<a href="${esc(url)}" target="_blank" rel="noreferrer">${text}</a>`,
  );
  return s;
}

export function renderMarkdown(src: string): string {
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  const out: string[] = [];
  let para: string[] = [];
  let listOpen = false;

  function flushPara() {
    if (para.length) {
      out.push(`<p>${inlineFmt(para.join(" "))}</p>`);
      para = [];
    }
  }
  function closeList() {
    if (listOpen) {
      out.push("</ul>");
      listOpen = false;
    }
  }

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) {
      flushPara();
      closeList();
      continue;
    }
    const h2 = /^##\s+(.*)$/.exec(line);
    if (h2) {
      flushPara(); closeList();
      out.push(`<h2>${inlineFmt(h2[1])}</h2>`);
      continue;
    }
    const h3 = /^###\s+(.*)$/.exec(line);
    if (h3) {
      flushPara(); closeList();
      out.push(`<h3>${inlineFmt(h3[1])}</h3>`);
      continue;
    }
    const li = /^[-*]\s+(.*)$/.exec(line);
    if (li) {
      flushPara();
      if (!listOpen) {
        out.push("<ul>");
        listOpen = true;
      }
      out.push(`<li>${inlineFmt(li[1])}</li>`);
      continue;
    }
    closeList();
    para.push(line.trim());
  }
  flushPara();
  closeList();
  return out.join("\n");
}
