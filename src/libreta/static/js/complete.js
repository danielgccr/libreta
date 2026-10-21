// Completion list and call signatures from jedi (DESIGN §6.6). The list is fetched when a
// name starts, on "." and '["' (or Ctrl+Space), and then filtered here while the name is
// typed; the signature on "(" and ",". Both sit at the caret, found with the <pre> marker
// (caretPoint). Accepting inserts through execCommand, so undo keeps working.
//
// A list that opened on its own while typing a name takes Enter only once an item has been
// chosen with the arrows: Enter at the end of a line must stay a line break. Tab always takes.

import * as api from "./api.js";
import { caretPoint, isPython, locate } from "./blocks.js";

const DEBOUNCE = 120; // ms
const TYPING = /^[\w"']*$/u; // what may be typed while the list stays open (names, keys)
const WORD = /(?<!\w)[^\W\d]\w*$/u; // a name being typed, right before the caret
const MOVES = new Set(["ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"]);

// {textarea, pos, items, shown, index, element, explicit, chosen}; pos: caret when fetched
let menu = null;
let tip = null; // the signature element
const timers = { complete: 0, signature: 0 };
const latest = { complete: 0, signature: 0 }; // only the latest answer of each kind shows

// Returns true when it handled the key (the caller then prevents the default).
export function handleAssistKey(event, textarea) {
  const mod = event.ctrlKey || event.metaKey;
  if (mod && event.code === "Space") {
    request("complete", textarea, { delay: 0 });
    return true;
  }
  if (MOVES.has(event.key) || (mod && event.key === "Enter")) closeAssist();
  if (menu?.textarea === textarea) {
    const plain = !mod && !event.shiftKey && !event.altKey;
    if ((event.key === "ArrowDown" || event.key === "ArrowUp") && plain) {
      select(menu.index + (event.key === "ArrowDown" ? 1 : -1));
      menu.chosen = true;
      return true;
    }
    if (event.key === "Enter" && plain && !(menu.explicit || menu.chosen)) closeMenu();
    else if ((event.key === "Tab" || event.key === "Enter") && plain) {
      accept(menu.shown[menu.index]);
      return true;
    }
  }
  if (event.key === "Escape" && (menu || tip)) {
    closeAssist();
    return true;
  }
  return false;
}

export function handleAssistInput(event) {
  const textarea = event.target;
  if (menu) {
    if (menu.textarea === textarea) filter();
    else closeMenu();
  }
  const data = event.data ?? ""; // null for deletions
  const before = textarea.value.slice(0, textarea.selectionStart);
  if (data.endsWith(".") || /\[["']$/.test(before)) request("complete", textarea);
  else if (!menu && /^\w$/u.test(data) && WORD.test(before)) {
    request("complete", textarea, { implicit: true });
  }
  if (data === "(" || data === ",") request("signature", textarea);
  else if (data === ")") closeTip();
}

export function closeAssist() {
  closeMenu();
  closeTip();
}

function request(kind, textarea, { delay = DEBOUNCE, implicit = false } = {}) {
  clearTimeout(timers[kind]);
  if (!helpful(textarea)) return;
  timers[kind] = setTimeout(async () => {
    const pos = textarea.selectionStart;
    // A line break or a space typed during the debounce: no name is being typed any more.
    if (implicit && !WORD.test(textarea.value.slice(0, pos))) return;
    const id = ++latest[kind];
    const { text, line, column } = point(textarea);
    let items;
    try {
      items = await api.assist(kind, text, line, column);
    } catch {
      return; // no help is not worth an alert
    }
    if (id !== latest[kind] || document.activeElement !== textarea) return;
    if (kind === "complete") openMenu(textarea, pos, items, !implicit);
    else showTip(textarea, items[0]);
  }, delay);
}

// In Markdown, only inside a `py` expression being typed.
function helpful(textarea) {
  if (isPython(textarea.closest(".block"))) return true;
  const { value, selectionStart } = textarea;
  const line = value.slice(value.lastIndexOf("\n", selectionStart - 1) + 1, selectionStart);
  return /`py\s+[^`]*$/.test(line);
}

// The caret in the document the server reads: 1-based line, 0-based column.
function point(textarea) {
  const block = textarea.closest(".block");
  const { text, lines } = locate(textarea.closest("main"));
  const before = textarea.value.slice(0, textarea.selectionStart).split("\n");
  const line = lines.get(block) + (isPython(block) ? 1 : 0) + before.length - 1;
  return { text, line, column: before.at(-1).length };
}

function place(element, textarea, above) {
  const { x, y, lineHeight } = caretPoint(textarea);
  element.style.left = `${x}px`;
  element.style.top = `${above ? y : y + lineHeight}px`;
}

function openMenu(textarea, pos, items, explicit) {
  closeMenu();
  const element = document.createElement("ul");
  element.className = "complete";
  element.setAttribute("role", "listbox");
  element.addEventListener("mousedown", (event) => {
    event.preventDefault(); // the textarea keeps the focus
    const li = event.target.closest("li");
    if (li) accept(menu.shown[li.dataset.i]);
  });
  document.body.append(element);
  menu = { textarea, pos, items, shown: [], index: 0, element, explicit, chosen: false };
  filter();
}

// Names that still match what was typed since the list came and would add something;
// _private ones only once "_" is typed.
function filter() {
  const { textarea, pos, items, element } = menu;
  const typed = textarea.value.slice(pos, textarea.selectionStart);
  if (textarea.selectionStart < pos || !TYPING.test(typed)) return closeMenu();
  menu.shown = items.filter((c) => {
    const prefix = c.name.slice(0, c.name.length - c.complete.length) + typed;
    const matches = c.complete.startsWith(typed) && c.complete !== typed;
    return matches && (!c.name.startsWith("_") || prefix.startsWith("_"));
  });
  if (!menu.shown.length) return closeMenu();
  element.replaceChildren(
    ...menu.shown.map((c, i) => {
      const li = document.createElement("li");
      li.dataset.i = i;
      li.setAttribute("role", "option");
      const type = document.createElement("span");
      type.className = "type";
      type.textContent = c.type;
      li.append(c.name, type);
      return li;
    }),
  );
  place(element, textarea, false);
  select(0);
}

function select(index) {
  const items = menu.element.children;
  menu.index = (index + items.length) % items.length;
  for (const li of items) li.classList.toggle("selected", li.dataset.i == menu.index);
  // Scroll the list only: scrollIntoView would also scroll the page.
  const { element } = menu;
  const li = items[menu.index];
  if (li.offsetTop < element.scrollTop) element.scrollTop = li.offsetTop;
  else if (li.offsetTop + li.offsetHeight > element.scrollTop + element.clientHeight)
    element.scrollTop = li.offsetTop + li.offsetHeight - element.clientHeight;
}

function accept(completion) {
  const { textarea, pos } = menu;
  const rest = completion.complete.slice(textarea.selectionStart - pos);
  closeMenu();
  if (rest) document.execCommand("insertText", false, rest);
}

function closeMenu() {
  menu?.element.remove();
  menu = null;
}

function showTip(textarea, signature) {
  closeTip();
  if (!signature) return;
  tip = document.createElement("div");
  tip.className = "signature";
  tip.append(`${signature.name}(`);
  signature.params.forEach((param, i) => {
    if (i) tip.append(", ");
    const span = document.createElement("span");
    span.textContent = param;
    if (i === signature.index) span.className = "current";
    tip.append(span);
  });
  tip.append(")");
  document.body.append(tip);
  place(tip, textarea, true);
}

function closeTip() {
  tip?.remove();
  tip = null;
}
