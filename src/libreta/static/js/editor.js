// Entry point: build the blocks, route keys, save, run.

import * as api from "./api.js";
import {
  appendOutput,
  caretLine,
  clearOutput,
  createBlock,
  focusBlock,
  insertPython,
  isPython,
  locate,
  normalize,
  paint,
  paintNotes,
  removePython,
  revealCaret,
  serialize,
} from "./blocks.js";
import { closeAssist, handleAssistInput, handleAssistKey } from "./complete.js";
import { handlePythonKey } from "./keys.js";

const main = document.getElementById("doc");
const titleInput = document.getElementById("title");
const dateLine = document.getElementById("date");
const doc = JSON.parse(document.getElementById("doc-data").textContent);
main.dataset.finalNewline = doc.finalNewline ? "1" : "";
// The YAML front matter is no block: its title is edited above the document and its date
// is the last save's, stamped by the server. The rest of it is kept as it is, unseen.
main.dataset.front = doc.front;
titleInput.value = doc.title;
showDate(doc.date);
main.values = doc.values; // of the Markdown before the first Python block
for (const b of doc.blocks) {
  const block = createBlock(b.kind, b.value, b);
  main.append(block);
  for (const item of b.output ?? []) appendOutput(block, item); // cached (DESIGN §5)
  if (b.values) block.values = b.values;
}
normalize(main);
if (doc.blocks.length) focusBlock(main.firstElementChild, "start");
else titleInput.focus(); // a new document starts with its title

// Notes sit at the height of their line, so they move whenever lines rewrap.
const paintAllNotes = () => main.querySelectorAll(".block.md").forEach(paintNotes);
paintAllNotes();
document.fonts.ready.then(paintAllNotes);
window.addEventListener("resize", paintAllNotes);

const pageTitle = document.title;
let saved = serialize(main); // what is on disk
let savedTitle = titleInput.value;
let allSelected = false; // Ctrl+A: the whole document, not one textarea

// Unsaved changes = the document differs from what was last saved; no flag to fall out of
// sync. ponytail: serializes the whole document per edit, cache per block if it gets slow.
const isDirty = () => serialize(main) !== saved || titleInput.value.trim() !== savedTitle.trim();
const showDirty = () => (document.title = (isDirty() ? "• " : "") + pageTitle);

function showDate(date) {
  const day = new Date(`${date}T00:00`);
  if (!date) dateLine.textContent = "";
  else if (isNaN(day)) dateLine.textContent = date;
  else dateLine.textContent = day.toLocaleDateString("es", { dateStyle: "long" });
}

titleInput.addEventListener("input", showDirty);
titleInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === "ArrowDown") {
    event.preventDefault();
    focusBlock(main.firstElementChild, "start");
  }
});

function selectAll(on) {
  allSelected = on;
  main.classList.toggle("all-selected", on);
}

async function save() {
  const title = titleInput.value;
  try {
    const result = await api.save(serialize(main), title);
    main.dataset.front = result.front;
    saved = result.text;
    savedTitle = title;
    showDate(result.date);
    showDirty();
  } catch (error) {
    alert(`No se ha podido guardar: ${error.message}`);
  }
}

// Python blocks from `block` on (or after it) no longer show what their code would produce.
function markStale(block, after = false) {
  for (let b = after ? block.nextElementSibling : block; b; b = b.nextElementSibling)
    if (isPython(b)) b.classList.add("stale");
}

// Ctrl+Enter: a Python block runs; in Markdown, its `py` expressions are evaluated. Runs
// queue on the server. When earlier blocks changed, the server first runs them again
// (DESIGN §4.5): each block's output comes after a {start: line} item naming it, and the
// values of the Markdown after a block (line 0: before the first) in a {values, line} item.
async function run(block) {
  const { text, lines } = locate(main);
  const python = new Map([...lines].filter(([b]) => isPython(b)).map(([b, line]) => [line, b]));
  let current = isPython(block) ? block : null; // the block whose output streams in
  if (current) {
    clearOutput(current);
    current.classList.add("running");
  }
  try {
    await api.run(text, lines.get(block), !current, (item) => {
      if (item.values) {
        const owner = item.line ? python.get(item.line) : main;
        if (owner) owner.values = item.values;
        paintAllNotes();
      } else if (item.start !== undefined) {
        current?.classList.remove("running");
        current = python.get(item.start); // undefined only if client and server disagree
        if (!current) return;
        markStale(current, true);
        current.classList.remove("stale");
        current.classList.add("running");
        clearOutput(current);
      } else if (current) {
        appendOutput(current, item);
      }
    });
  } catch (error) {
    if (current) appendOutput(current, { mime: "error", content: `${error.message}\n` });
    else alert(error.message);
  } finally {
    current?.classList.remove("running");
    block.classList.remove("running");
  }
}

main.addEventListener("input", (event) => {
  const block = event.target.closest(".block");
  if (isPython(block)) markStale(block);
  delete block.dataset.virtual;
  paint(block);
  if (!isPython(block)) paintNotes(block);
  handleAssistInput(event);
  revealCaret(event.target);
  showDirty();
});

document.addEventListener("selectionchange", () => {
  if (document.activeElement.tagName === "TEXTAREA") revealCaret(document.activeElement);
});

// The textarea is exactly as big as its <pre>: it must never scroll on its own.
main.addEventListener(
  "scroll",
  (event) => {
    if (event.target.tagName === "TEXTAREA") event.target.scrollTop = event.target.scrollLeft = 0;
  },
  true,
);

document.addEventListener("keydown", (event) => {
  const mod = event.ctrlKey || event.metaKey;
  const key = event.key.toLowerCase();
  if (allSelected && !["Control", "Meta", "Shift", "Alt"].includes(event.key)) {
    if (mod && key === "c") {
      event.preventDefault();
      navigator.clipboard.writeText(serialize(main));
      return;
    }
    if (!(mod && key === "a")) selectAll(false);
  }
  // First: with the completion list open, arrows, Enter, Tab and Escape are its own.
  if (event.target.tagName === "TEXTAREA" && handleAssistKey(event, event.target)) {
    event.preventDefault();
    return;
  }
  if (mod && key === "s") {
    event.preventDefault();
    save();
    return;
  }
  if (mod && !event.altKey && key === "a" && event.target !== titleInput) {
    event.preventDefault();
    selectAll(true);
    return;
  }
  if (event.key === "Escape" && main.querySelector(".running")) {
    event.preventDefault();
    api.interrupt();
    return;
  }
  if (mod && event.shiftKey && event.key === "F10") {
    event.preventDefault(); // RStudio's "restart R"
    api.restart();
    return;
  }

  const textarea = event.target;
  if (textarea.tagName !== "TEXTAREA") return;
  const block = textarea.closest(".block");

  if (mod && event.altKey && event.code === "KeyI") {
    event.preventDefault();
    insertPython(main, textarea);
    markStale(document.activeElement.closest(".block")); // a new block changes the chain
    paintAllNotes();
    showDirty();
    return;
  }
  if (mod && event.key === "Enter") {
    event.preventDefault();
    if (isPython(block)) {
      run(block);
      focusBlock(block.nextElementSibling, "start");
    } else if (block.querySelector(".md-py")) {
      run(block);
    }
    return;
  }
  if (isPython(block)) {
    if (event.key === "Backspace" && !mod && textarea.value === "") {
      event.preventDefault();
      markStale(block, true);
      removePython(block);
      normalize(main);
      paintAllNotes();
      showDirty();
      return;
    }
    if (handlePythonKey(event, textarea)) {
      event.preventDefault();
      return;
    }
  }
  if ((event.key === "ArrowUp" || event.key === "ArrowDown") && !mod && !event.shiftKey && !event.altKey) {
    const up = event.key === "ArrowUp";
    const target = up ? block.previousElementSibling : block.nextElementSibling;
    if (!target && !up) return;
    const { line, lines } = caretLine(textarea);
    if (up ? line === 0 : line === lines - 1) {
      event.preventDefault();
      if (target) focusBlock(target, up ? "end" : "start");
      else titleInput.focus(); // above the first block, the title
    }
  }
});

document.addEventListener("mousedown", () => {
  selectAll(false);
  closeAssist();
});
main.addEventListener("focusout", closeAssist);
window.addEventListener("beforeunload", (event) => {
  if (isDirty()) event.preventDefault();
});
