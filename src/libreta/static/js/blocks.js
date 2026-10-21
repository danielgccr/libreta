// The document as a sequence of blocks: <section class="block md|py"> holding a textarea
// over a highlighted <pre> (DESIGN §6.1). A block's last line ending is implied, not shown.
//
// Virtual blocks are empty Markdown blocks the editor adds so there is always somewhere to
// type: before the first and after the last Python block, and between two Python blocks.
// They serialize to nothing until typed into.

import { escapeHtml, highlightPython } from "./py-highlight.js";
import { highlightMarkdown } from "./md-highlight.js";

const HEADING = /^ {0,3}(#{1,6})(?:[ \t]|$)/;
const PYTHON_ATTRS =
  'wrap="off" spellcheck="false" autocapitalize="off" autocorrect="off" autocomplete="off" aria-label="Python"';
const MARKDOWN_ATTRS = 'aria-label="Markdown"';

export const isPython = (block) => block.classList.contains("py");
export const textareaOf = (block) => block.querySelector("textarea");

export function createBlock(kind, value = "", fences = {}) {
  const block = document.createElement("section");
  const python = kind === "python";
  block.className = `block ${python ? "py" : "md"}`;
  const layers =
    `<div class="layers"><pre class="hl" aria-hidden="true"></pre>` +
    `<textarea rows="1" ${python ? PYTHON_ATTRS : MARKDOWN_ATTRS}></textarea></div>`;
  block.innerHTML = python ? `<div class="scroll">${layers}</div><div class="output"></div>` : layers;
  if (python) {
    block.dataset.open = fences.open ?? "```python\n";
    block.dataset.close = fences.close ?? "```\n";
  }
  textareaOf(block).value = value; // a fresh textarea: there is no undo history to keep
  paint(block);
  return block;
}

function virtualBlock() {
  const block = createBlock("markdown");
  block.dataset.virtual = "1";
  return block;
}

export function paint(block) {
  const value = textareaOf(block).value;
  const pre = block.querySelector("pre");
  // The trailing \n gives a final empty line its height, as in the textarea.
  pre.innerHTML = (isPython(block) ? highlightPython(value) : highlightMarkdown(value)) + "\n";
  if (!isPython(block)) {
    const heading = value.match(HEADING);
    if (heading) block.dataset.heading = heading[1].length;
    else delete block.dataset.heading;
  }
}

// Markdown before, after and between Python blocks (see "virtual blocks" above).
export function normalize(main) {
  let prev = null;
  for (const block of [...main.children]) {
    if (isPython(block) && (!prev || isPython(prev))) block.before(virtualBlock());
    prev = block;
  }
  if (!prev || isPython(prev)) main.append(virtualBlock());
}

function blockData(main) {
  return [...main.querySelectorAll(".block")].map((block) => ({
    kind: isPython(block) ? "python" : "markdown",
    value: textareaOf(block).value,
    open: block.dataset.open,
    close: block.dataset.close,
    virtual: "virtual" in block.dataset,
  }));
}

export function serialize(main) {
  return serializeBlocks(blockData(main), main.dataset.finalNewline === "1");
}

// The document and the 1-based line where each block starts in it (how /run names a block):
// a Map from block to line.
export function locate(main) {
  const { text, starts } = layout(blockData(main), main.dataset.finalNewline === "1");
  const lines = new Map();
  main.querySelectorAll(".block").forEach((block, i) => {
    lines.set(block, text.slice(0, starts[i]).split("\n").length);
  });
  return { text, lines };
}

// Twin of serialize_editor() in tests/test_app.py, the inverse of app.editor_blocks().
export function serializeBlocks(blocks, finalNewline) {
  return layout(blocks, finalNewline).text;
}

function layout(blocks, finalNewline) {
  const parts = blocks.map((b) => {
    if (b.kind === "markdown") return b.virtual && !b.value ? "" : b.value + "\n";
    const open = b.open.endsWith("\n") ? b.open : b.open + "\n";
    return { open, body: b.value ? b.value + "\n" : "", close: b.close };
  });
  let text = "";
  const starts = [];
  parts.forEach((part, i) => {
    starts.push(text.length);
    if (typeof part === "string") return (text += part);
    let close = part.close;
    // A fence left open at the end of the file must close once something follows it.
    if (!close && parts.slice(i + 1).some((p) => p !== "")) close = fenceMarker(part.open) + "\n";
    text += part.open + part.body + close;
  });
  if (!finalNewline && text.endsWith("\n")) text = text.slice(0, -1);
  return { text, starts };
}

const fenceMarker = (open) => open.match(/(`{3,}|~{3,})/)[1];

export function focusBlock(block, where) {
  const textarea = textareaOf(block);
  textarea.focus();
  const pos = where === "end" ? textarea.value.length : 0;
  textarea.setSelectionRange(pos, pos);
}

// Ctrl+Alt+I. In Markdown, split the block at the caret and put a Python block in between;
// in Python, add one after. The tail leaves the block via execCommand, so undo keeps working
// inside it (undo cannot follow text across blocks).
export function insertPython(main, textarea) {
  const block = textarea.closest(".block");
  const python = createBlock("python");
  if (isPython(block)) {
    block.after(python);
  } else {
    const value = textarea.value;
    const pos = textarea.selectionStart;
    // The caret's line break becomes the fences' own line breaks.
    const cut = pos > 0 && value[pos - 1] === "\n" ? pos - 1 : pos;
    const rest = value.slice(pos).replace(/^\n/, "");
    if (cut < value.length) {
      textarea.setSelectionRange(cut, value.length);
      document.execCommand("delete");
    }
    if (cut === 0) block.dataset.virtual = "1";
    block.after(python);
    if (rest) python.after(createBlock("markdown", rest));
  }
  normalize(main);
  focusBlock(python, "start");
}

// Backspace in an empty Python block: remove it and join the Markdown around it.
export function removePython(block) {
  const prev = block.previousElementSibling;
  const next = block.nextElementSibling;
  block.remove();
  if ("virtual" in next.dataset) {
    next.remove();
    focusBlock(prev, "end");
  } else if ("virtual" in prev.dataset) {
    prev.remove();
    focusBlock(next, "start");
  } else {
    const textarea = textareaOf(prev);
    const join = textarea.value.length;
    focusBlock(prev, "end");
    document.execCommand("insertText", false, "\n" + textareaOf(next).value);
    textarea.setSelectionRange(join, join);
    next.remove();
  }
}

// Caret position measured with a marker <span> in the <pre>, which has the textarea's exact
// metrics (soft wraps included); then the real colours go back.
function caretOffset(textarea) {
  const block = textarea.closest(".block");
  const pre = block.querySelector("pre");
  const { value, selectionEnd: pos } = textarea;
  pre.innerHTML = `${escapeHtml(value.slice(0, pos))}<span></span>${escapeHtml(value.slice(pos))}\n`;
  const box = pre.getBoundingClientRect();
  const marker = pre.querySelector("span").getBoundingClientRect();
  const lineHeight = parseFloat(getComputedStyle(pre).lineHeight);
  paint(block);
  return { left: marker.left - box.left, top: marker.top - box.top, height: box.height, lineHeight };
}

// Page coordinates of the caret's line: where completion lists and signatures go.
export function caretPoint(textarea) {
  const { left, top, lineHeight } = caretOffset(textarea);
  const box = textarea.closest(".block").querySelector("pre").getBoundingClientRect();
  return { x: box.left + left + scrollX, y: box.top + top + scrollY, lineHeight };
}

// Visual line of the caret and the block's number of visual lines.
export function caretLine(textarea) {
  const { top, height, lineHeight } = caretOffset(textarea);
  return { line: Math.floor(top / lineHeight), lines: Math.round(height / lineHeight) };
}

// Python lines do not wrap and the textarea never scrolls itself: keep the caret inside the
// block's horizontal scroll (browsers do not reliably scroll that outer box while typing).
export function revealCaret(textarea) {
  const scroll = textarea.closest(".scroll");
  if (!scroll || scroll.scrollWidth <= scroll.clientWidth) return;
  const { left } = caretOffset(textarea);
  const margin = 4 * (parseFloat(getComputedStyle(scroll).fontSize) || 16);
  if (left < scroll.scrollLeft + margin) scroll.scrollLeft = left - margin;
  else if (left > scroll.scrollLeft + scroll.clientWidth - margin)
    scroll.scrollLeft = left - scroll.clientWidth + margin;
}

// Output of a Python block, inside its grey block. It is never focusable (DESIGN §2).
export function clearOutput(block) {
  block.querySelector(".output").replaceChildren();
}

const FIGURE_WIDTH = 6.8 * 96; // px: figure.figsize in libreta/_mpl.py, in CSS pixels

export function appendOutput(block, { mime, content, base64 }) {
  const output = block.querySelector(".output");
  const last = output.lastElementChild;
  if ((mime === "stdout" || mime === "stderr") && last?.dataset.stream === mime) {
    last.append(content); // ponytail: no \r handling, progress bars print every frame
    return;
  }
  let element;
  if (mime === "text/html") {
    element = document.createElement("div");
    element.innerHTML = content; // the user's own code produced it, as in Jupyter
  } else if (mime.startsWith("image/")) {
    element = new Image(); // <img>, not inline SVG: matplotlib's ids would clash between figures
    element.alt = "";
    // SVG at the scale where a default matplotlib figure (6.8in) fills the block.
    if (mime === "image/svg+xml")
      element.onload = () => (element.style.width = `${(100 * element.naturalWidth) / FIGURE_WIDTH}%`);
    element.src = base64
      ? `data:${mime};base64,${base64}`
      : `data:${mime};charset=utf-8,${encodeURIComponent(content)}`;
  } else {
    element = document.createElement("pre"); // streams, errors, text/plain, text/markdown (v1)
    element.textContent = content;
  }
  element.className = `out ${mime.replace(/\W/g, "-")}`;
  if (mime === "stdout" || mime === "stderr") element.dataset.stream = mime;
  output.append(element);
}

// Values of the `py` expressions of a Markdown block, in the right margin at the height of
// their line (DESIGN §6.5). They live on the Python block above (or on main, before the
// first one) as {expression: {text} | {error}}; the <pre>'s .md-py spans give the heights.
export function paintNotes(block) {
  let owner = block.previousElementSibling;
  while (owner && !isPython(owner)) owner = owner.previousElementSibling;
  const values = (owner ?? block.parentElement).values ?? {};
  const pre = block.querySelector("pre");
  const top = pre.getBoundingClientRect().top;
  const lines = new Map(); // height -> values on that visual line
  for (const span of pre.querySelectorAll(".md-py")) {
    const value = values[span.textContent.replace(/^`+|`+$/g, "").slice(2).trim()];
    if (!value) continue;
    const y = Math.round(span.getBoundingClientRect().top - top);
    lines.set(y, [...(lines.get(y) ?? []), value]);
  }
  let notes = block.querySelector(".notes");
  if (!notes) {
    notes = document.createElement("div");
    notes.className = "notes";
    notes.setAttribute("aria-hidden", "true");
    block.querySelector(".layers").append(notes);
  }
  notes.replaceChildren(
    ...[...lines].map(([y, line]) => {
      const note = document.createElement("div");
      note.className = "note";
      note.style.top = `${y}px`;
      for (const value of line) {
        const span = document.createElement("span");
        span.textContent = value.text ?? value.error;
        if (value.error) span.className = "error";
        note.append(span);
      }
      return note;
    }),
  );
}
