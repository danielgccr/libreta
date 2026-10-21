// Python editing keys (DESIGN §6.3). Every edit goes through execCommand so the browser's
// undo history survives (assigning textarea.value would wipe it).

const INDENT = "    ";
const DEDENT_AFTER = /^\s*(return|pass|break|continue|raise)\b/;

// Returns true when it handled the key (the caller then prevents the default).
export function handlePythonKey(event, textarea) {
  const mod = event.ctrlKey || event.metaKey;
  if (event.key === "Tab" && !mod && !event.altKey) {
    if (event.shiftKey) mapLines(textarea, (line) => line.replace(/^ {1,4}/, ""));
    else if (spansLines(textarea)) mapLines(textarea, (line) => (line ? INDENT + line : line));
    else insert(textarea, INDENT);
    return true;
  }
  // Shift+Enter too: it is how a line breaks while the completion list is open.
  if (event.key === "Enter" && !mod && !event.altKey) {
    newline(textarea);
    return true;
  }
  if (event.key === "Backspace" && !mod && !event.shiftKey && !event.altKey) return backspace(textarea);
  if (mod && (event.key === "/" || event.code === "Slash")) {
    toggleComment(textarea);
    return true;
  }
  return false;
}

function insert(textarea, text) {
  document.execCommand("insertText", false, text);
}

const lineStart = (value, pos) => value.lastIndexOf("\n", pos - 1) + 1;

function spansLines(textarea) {
  const { value, selectionStart, selectionEnd } = textarea;
  return value.slice(selectionStart, selectionEnd).includes("\n");
}

// Replace the whole lines touched by the selection with fn(line), keeping them selected
// (or, for a caret, keeping it on the same character).
function mapLines(textarea, fn) {
  const { value, selectionStart, selectionEnd } = textarea;
  const start = lineStart(value, selectionStart);
  // A selection ending at column 0 does not include that line.
  const last = selectionEnd > selectionStart && value[selectionEnd - 1] === "\n" ? selectionEnd - 1 : selectionEnd;
  let end = value.indexOf("\n", last);
  if (end < 0) end = value.length;
  const old = value.slice(start, end);
  const replaced = old.split("\n").map(fn).join("\n");
  if (replaced === old) return;
  textarea.setSelectionRange(start, end);
  insert(textarea, replaced);
  if (selectionStart === selectionEnd) {
    const pos = Math.max(start, selectionStart + replaced.length - old.length);
    textarea.setSelectionRange(pos, pos);
  } else {
    textarea.setSelectionRange(start, start + replaced.length);
  }
}

function newline(textarea) {
  const { value, selectionStart } = textarea;
  const line = value.slice(lineStart(value, selectionStart), selectionStart);
  let indent = line.match(/^ */)[0];
  if (line.replace(/#.*$/, "").trimEnd().endsWith(":")) indent += INDENT;
  else if (DEDENT_AFTER.test(line)) indent = indent.slice(INDENT.length);
  insert(textarea, "\n" + indent);
}

// In the indentation, delete back to the previous tab stop.
function backspace(textarea) {
  const { value, selectionStart, selectionEnd } = textarea;
  if (selectionStart !== selectionEnd) return false;
  const start = lineStart(value, selectionStart);
  const before = value.slice(start, selectionStart);
  if (!before || /[^ ]/.test(before)) return false;
  const n = ((before.length - 1) % INDENT.length) + 1;
  textarea.setSelectionRange(selectionStart - n, selectionStart);
  document.execCommand("delete");
  return true;
}

function toggleComment(textarea) {
  const { value, selectionStart, selectionEnd } = textarea;
  const start = lineStart(value, selectionStart);
  let end = value.indexOf("\n", selectionEnd);
  const lines = value.slice(start, end < 0 ? undefined : end).split("\n");
  const code = lines.filter((line) => line.trim());
  if (code.every((line) => /^\s*#/.test(line))) {
    mapLines(textarea, (line) => line.replace(/^(\s*)# ?/, "$1"));
  } else {
    const indent = Math.min(...code.map((line) => line.match(/^ */)[0].length));
    mapLines(textarea, (line) => (line.trim() ? line.slice(0, indent) + "# " + line.slice(indent) : line));
  }
}
