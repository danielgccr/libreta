// Spanish and English, as in libreta/i18n.py: the Spanish text is the key, and the page
// brings the translations into the server's language (none for Spanish), which is also
// its lang.

const MESSAGES = JSON.parse(document.getElementById("messages")?.textContent ?? "{}");

export const lang = document.documentElement.lang;

// `text` (Spanish) in the page's language, with its {placeholders} filled from `values`.
export function tr(text, values = {}) {
  return (MESSAGES[text] ?? text).replace(/\{(\w+)\}/g, (match, key) => values[key] ?? match);
}
