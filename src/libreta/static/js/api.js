// Calls to the server. Output streams back as NDJSON, one {mime, content|base64} per line.

async function request(path, options = {}) {
  const response = await fetch(path, { method: "POST", ...options });
  if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
  return response;
}

export function save(text) {
  return request("/doc", {
    method: "PUT",
    headers: { "Content-Type": "text/plain; charset=utf-8" },
    body: text,
  });
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
export const restart = () => request("/restart");

// kind "complete" or "signature": jedi's help at a cursor of the document (DESIGN §6.6).
export async function assist(kind, text, line, column) {
  const response = await request(`/${kind}`, {
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, line, column }),
  });
  return response.json();
}
