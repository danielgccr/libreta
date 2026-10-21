// Calls to the server, under the document's own URL (/edit/<path>/run...). Output streams
// back as NDJSON, one {mime, content|base64} per line.

const BASE = location.pathname;

async function request(path, options = {}) {
  const response = await fetch(BASE + path, { method: "POST", ...options });
  if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
  return response;
}

// Saving sets the title in the front matter and stamps the date: {text, front, date} back.
export async function save(text, title) {
  const response = await request("/doc", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, title }),
  });
  return response.json();
}

// `line`: where a Python block opens, or with `inline`, where a Markdown block starts.
export async function run(text, line, inline, onItem) {
  const response = await request("/run", {
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, line, inline }),
  });
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    const lines = (buffer + value).split("\n");
    buffer = lines.pop();
    for (const line of lines) if (line) onItem(JSON.parse(line));
  }
}

export const interrupt = () => request("/interrupt");
export const modules = async () => (await request("/modules", { method: "GET" })).json();
export const restart = () => request("/restart");
// The page goes (tab closed, another document, the index): its worker with it. A beacon,
// since a fetch would not outlive the page.
export const close = () => navigator.sendBeacon(BASE + "/restart");

// kind "complete" or "signature": jedi's help at a cursor of the document (DESIGN §6.6).
export async function assist(kind, text, line, column) {
  const response = await request(`/${kind}`, {
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, line, column }),
  });
  return response.json();
}
