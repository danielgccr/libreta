// Entry point: build the blocks, route keys, save, run.

import * as api from "./api.js";
import {
  appendOutput,
  caretLine,
  clearOutput,
  createBlock,
  focusBlock,
  followHistory,
  guardHistory,
  insertFootnote,
  insertPython,
  isPython,
  locate,
  normalize,
  paint,
  paintNotes,
  removePython,
  revealCaret,
  serialize,
  textareaOf,
} from "./blocks.js";
import { closeAssist, handleAssistInput, handleAssistKey } from "./complete.js";
import { lang, tr } from "./i18n.js";
import { handlePythonKey } from "./keys.js";
import { setModules } from "./py-highlight.js";

const main = document.getElementById("doc");
const titleInput = document.getElementById("title");
const dateLine = document.getElementById("date");
const status = document.getElementById("status");
const doc = JSON.parse(document.getElementById("doc-data").textContent);
main.dataset.finalNewline = doc.finalNewline ? "1" : "";
setModules(doc.modules); // before the blocks paint
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
  if (b.stale) setStale(block, tr("Ha cambiado {file}", { file: b.stale })); // its data (DESIGN §5)
}
normalize(main);
// The caret starts in the document, or in the title of a new one; the page stays at its top.
if (doc.blocks.length) {
  const first = main.querySelector("textarea");
  first.setSelectionRange(0, 0);
  first.focus({ preventScroll: true });
} else titleInput.focus();

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

// Screen readers hear how runs and saves end (aria-live="polite"). Emptied first, so the
// same message twice in a row is still read out.
function announce(message) {
  status.textContent = "";
  setTimeout(() => (status.textContent = message), 50);
}

function showDate(date) {
  const day = new Date(`${date}T00:00`);
  if (!date) dateLine.textContent = "";
  else if (isNaN(day)) dateLine.textContent = date;
  else dateLine.textContent = day.toLocaleDateString(lang, { dateStyle: "long" });
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
    announce(tr("Guardado"));
  } catch (error) {
    alert(tr("No se ha podido guardar: {error}", { error: error.message }));
  }
}

// The Markdown after `block` (or from it, if it is Markdown) up to the next Python block:
// the one whose notes show `block`'s values.
function paintNotesAfter(block) {
  let b = isPython(block) ? block.nextElementSibling : block;
  for (; b && !isPython(b); b = b.nextElementSibling) paintNotes(b);
}

// A Python block inserted or removed at `block` moves the notes just before it and after it.
function paintNotesNear(block) {
  const prev = block.previousElementSibling;
  if (prev && !isPython(prev)) paintNotes(prev);
  paintNotesAfter(block);
}

const ABOVE = tr("Ha cambiado o se ha vuelto a ejecutar un bloque anterior");

// Python blocks from `block` on (or after it) no longer show what their code would produce.
// Each says why, on hover and to screen readers: `reason` the first, `rest` the others.
function markStale(block, after = false, reason = tr("Ha cambiado su código"), rest = ABOVE) {
  let first = !after;
  for (let b = after ? block.nextElementSibling : block; b; b = b.nextElementSibling) {
    if (!isPython(b)) continue;
    setStale(b, first ? reason : rest);
    first = false;
  }
}

function setStale(block, reason) {
  block.classList.add("stale");
  block.querySelector(".output").title = reason;
  textareaOf(block).setAttribute("aria-description", reason);
}

function clearStale(block) {
  block.classList.remove("stale");
  block.querySelector(".output").removeAttribute("title");
  textareaOf(block).removeAttribute("aria-description");
}

// Backspace or Delete on an empty Python block: it goes and the Markdown around it joins.
function dropPython(python) {
  markStale(python, true);
  removePython(python);
  normalize(main);
  paintNotesNear(document.activeElement.closest(".block"));
  showDirty();
}

// Ctrl+Enter: a Python block runs; in Markdown, its `py` expressions are evaluated. Runs
// queue on the server. When earlier blocks changed, the server first runs them again
// (DESIGN §4.5): each block's output comes after a {start: line} item naming it, and the
// values of the Markdown after a block (line 0: before the first) in a {values, line} item.
async function run(block) {
  const { text, lines } = locate(main);
  const python = new Map([...lines].filter(([b]) => isPython(b)).map(([b, line]) => [line, b]));
  let current = isPython(block) ? block : null; // the block whose output streams in
  const failed = new Set(); // blocks with an error, for the announcement
  if (current) {
    clearOutput(current);
    current.classList.add("running");
  }
  try {
    await api.run(text, lines.get(block), !current, (item) => {
      if (item.values) {
        const owner = item.line ? python.get(item.line) : main;
        if (!owner) return;
        owner.values = item.values;
        paintNotesAfter(owner === main ? main.firstElementChild : owner);
      } else if (item.start !== undefined) {
        current?.classList.remove("running");
        current = python.get(item.start); // undefined only if client and server disagree
        if (!current) return;
        markStale(current, true);
        clearStale(current);
        current.classList.add("running");
        clearOutput(current);
      } else if (current) {
        appendOutput(current, item);
        if (item.mime === "error") failed.add(current);
      }
    });
    if (!isPython(block)) announce(tr("Valores actualizados"));
    else {
      const n = [...main.querySelectorAll(".block.py")].indexOf(block) + 1;
      if (failed.has(block)) announce(tr("Bloque {n}: error", { n }));
      else if (failed.size) announce(tr("Bloque {n} ejecutado, con errores en bloques anteriores", { n }));
      else announce(tr("Bloque {n} ejecutado", { n }));
    }
  } catch (error) {
    if (current) appendOutput(current, { mime: "error", content: `${error.message}\n` });
    else alert(error.message);
    announce(tr("No se ha podido ejecutar: {error}", { error: error.message }));
  } finally {
    current?.classList.remove("running");
    block.classList.remove("running");
  }
}

main.addEventListener("beforeinput", (event) => {
  if (event.inputType.startsWith("history")) guardHistory(event);
});

main.addEventListener("input", (event) => {
  const block = event.target.closest(".block");
  if (isPython(block)) markStale(block);
  delete block.dataset.virtual;
  paint(block);
  if (!isPython(block)) paintNotes(block);
  if (event.inputType?.startsWith("history") && followHistory(main, event.target, event.inputType)) {
    markStale(block, true);
    paintNotesNear(block);
  }
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
    // In a Python block the native one selects the code; once all of it is, the document.
    const t = event.target;
    if (t.closest(".block.py") && (t.selectionStart > 0 || t.selectionEnd < t.value.length)) {
      return;
    }
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
    const python = document.activeElement.closest(".block");
    markStale(python); // a new block changes the chain
    paintNotesNear(python);
    showDirty();
    return;
  }
  if (mod && event.altKey && event.code === "KeyF" && !isPython(block)) {
    event.preventDefault();
    insertFootnote(main, textarea);
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
  // Delete at the end of Markdown, or in an empty Python block, removes that empty block
  // like Backspace does from inside it.
  if (event.key === "Delete" && !mod && !event.shiftKey && !event.altKey) {
    const atEnd = textarea.selectionStart === textarea.value.length && textarea.selectionEnd === textarea.value.length;
    const python = isPython(block) ? block : atEnd && block.nextElementSibling;
    if (python && isPython(python) && textareaOf(python).value === "") {
      event.preventDefault();
      dropPython(python);
      return;
    }
  }
  if (isPython(block)) {
    if (event.key === "Backspace" && !mod && textarea.value === "") {
      event.preventDefault();
      dropPython(block);
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

// Back from the terminal (`uv add pandas`): imports greyed out may be installed now, and the
// data a block read may have changed.
let moduleList = (doc.modules ?? []).join();
window.addEventListener("focus", async () => {
  const { text, lines } = locate(main);
  api.stale(text).then((changed) => {
    const reason = tr("Ha cambiado {file}", { file: changed?.file });
    for (const [block, at] of lines)
      if (at === changed?.line && isPython(block)) markStale(block, false, reason, reason);
  }, () => {});
  const names = await api.modules().catch(() => null);
  if (!names || names.join() === moduleList) return;
  moduleList = names.join();
  setModules(names);
  main.querySelectorAll(".block.py").forEach(paint);
});

document.addEventListener("mousedown", () => {
  selectAll(false);
  closeAssist();
});
main.addEventListener("focusout", closeAssist);
window.addEventListener("pagehide", api.close);
window.addEventListener("beforeunload", (event) => {
  if (isDirty()) event.preventDefault();
});
