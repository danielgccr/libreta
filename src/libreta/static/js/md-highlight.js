// Markdown colouring for the overlay. Colours only (DESIGN §6.2): headings darker, syntax
// markers muted, inline code with its background, links and footnote labels in --accent,
// `py ...` apart, and TeX math between dollars as Pandoc reads it (tex_math_dollars): no
// KaTeX, just colour.

import { escapeHtml } from "./py-highlight.js";

const FENCE_OPEN = /^ {0,3}(`{3,}|~{3,})(.*)$/;
const FENCE_CLOSE = /^ {0,3}(`{3,}|~{3,})[ \t]*$/;
const HEADING = /^( {0,3}#{1,6})([ \t].*|)$/;
const RULE = /^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/;
const QUOTE = /^( {0,3}(?:>[ \t]?)+)(.*)$/;
const ITEM = /^([ \t]*(?:[-+*]|\d{1,9}[.)]))([ \t].*|)$/;
const NOTE_DEF = /^( {0,3}\[\^[^[\]]+\]:)(.*)$/; // [^1]: footnote text (labels may have spaces)
const DISPLAY_OPEN = /^ {0,3}\$\$(?!.*\$\$)/; // $$ whose closing $$ comes on a later line

const INLINE = new RegExp(
  [
    String.raw`(?<esc>\\[!-/:-@[-\x60{-~])`,
    String.raw`(?<code>(?<tick>\x60+)(?<content>[^\x60](?:[^]*?[^\x60])?)\k<tick>(?!\x60))`,
    // $$display$$, or $inline$: no space inside the dollars, no digit after ($20 and $30).
    String.raw`(?<math>(?<dd>\$\$)(?<dc>.+?)\$\$|\$(?=[^\s$])(?<ic>[^$]*?[^\s\\$])\$(?!\d))`,
    // Math still being typed: a $ with no closing one up to the end of the line. Not before
    // a digit, so that a price stays prose.
    String.raw`(?<tex>(?<td>\$\$?)(?=[^\s$\d])(?<tc>[^$]*)$)`,
    String.raw`(?<auto><https?:\/\/[^>\s]+>)`,
    // Footnote reference, [^1], or one still being typed: no ] up to the end of the line.
    String.raw`(?<note>\[\^(?<label>[^[\]]+)(?<close>\])|\[\^(?<typed>[^[\]]*)$)`,
    String.raw`(?<link>(?<open>!?\[)(?<text>[^\]\n]*)(?<target>\]\([^)\n]*\)))`,
    String.raw`(?<star>(?<sd>\*\*|\*|~~)(?=[^\s*~])(?<sc>.+?)(?<=\S)\k<sd>)`,
    String.raw`(?<under>(?<![\p{L}\p{N}])(?<ud>__|_)(?=[^\s_])(?<uc>.+?)(?<=\S)\k<ud>(?![\p{L}\p{N}]))`,
  ].join("|"),
  "gu",
);

const span = (cls, html) => `<span class="${cls}">${html}</span>`;
const mark = (s) => span("md-mark", escapeHtml(s));
const math = (s) => span("md-math", escapeHtml(s));

export function highlightMarkdown(text) {
  let fence = null; // marker of the open fence (```bash and friends: prose for libreta)
  let display = false; // inside $$ ... $$ spanning lines (a blank line ends it, as in Pandoc)
  return text
    .split("\n")
    .map((line) => {
      if (fence) {
        const close = line.match(FENCE_CLOSE);
        if (close && close[1][0] === fence[0] && close[1].length >= fence.length) fence = null;
        return span("md-fence", escapeHtml(line));
      }
      const open = line.match(FENCE_OPEN);
      if (open && !(open[1][0] === "`" && open[2].includes("`"))) {
        fence = open[1];
        return span("md-fence", escapeHtml(line));
      }
      if (display && line.trim()) {
        const end = line.indexOf("$$");
        if (end < 0) return math(line);
        display = false;
        return math(line.slice(0, end)) + mark("$$") + inline(line.slice(end + 2));
      }
      display = false;
      if (DISPLAY_OPEN.test(line)) {
        display = true;
        const start = line.indexOf("$$");
        return escapeHtml(line.slice(0, start)) + mark("$$") + math(line.slice(start + 2));
      }
      let m;
      if ((m = line.match(HEADING))) return span("md-h", mark(m[1]) + inline(m[2]));
      if (RULE.test(line)) return mark(line);
      if ((m = line.match(QUOTE))) return mark(m[1]) + inline(m[2]);
      if ((m = line.match(NOTE_DEF))) return mark(m[1]) + inline(m[2]);
      if ((m = line.match(ITEM))) return mark(m[1]) + inline(m[2]);
      return inline(line);
    })
    .join("\n");
}

function inline(text) {
  let html = "";
  let last = 0;
  for (const m of text.matchAll(INLINE)) {
    const g = m.groups;
    html += escapeHtml(text.slice(last, m.index));
    last = m.index + m[0].length;
    if (g.esc) html += mark("\\") + escapeHtml(g.esc.slice(1));
    else if (g.code) {
      const cls = /^py\s/.test(g.content) ? "md-py" : "md-code";
      html += span(cls, mark(g.tick) + escapeHtml(g.content) + mark(g.tick));
    } else if (g.math) {
      const dollars = g.dd ?? "$";
      html += mark(dollars) + math(g.dc ?? g.ic) + mark(dollars);
    } else if (g.tex) html += mark(g.td) + math(g.tc); else if (g.auto) html += span("md-link", escapeHtml(g.auto));
    else if (g.note)
      html += mark("[^") + span("md-link", escapeHtml(g.label ?? g.typed)) + (g.close ? mark("]") : "");
    else if (g.link) html += mark(g.open) + span("md-link", escapeHtml(g.text)) + mark(g.target);
    else if (g.star) html += mark(g.sd) + inline(g.sc) + mark(g.sd);
    else html += mark(g.ud) + inline(g.uc) + mark(g.ud);
  }
  return html + escapeHtml(text.slice(last));
}
