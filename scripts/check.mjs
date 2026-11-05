import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Script } from 'node:vm';

const html = readFileSync('index.html', 'utf8');
const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)]
  .filter(([, attributes]) => !/\bsrc\s*=/i.test(attributes));
assert(scripts.length > 0, 'index.html must contain application JavaScript');
for (const [index, [, , source]] of scripts.entries()) {
  new Script(source, { filename: `index.html:inline-script-${index + 1}` });
}

assert(!html.includes('showOpenFilePicker'), 'Persistence must use the API');
assert(!html.includes('showSaveFilePicker'), 'Persistence must use the API');
assert(!html.includes("const DB_FILE"), 'Persistence must use the API');
console.log(`Validated ${scripts.length} inline script(s) and API persistence.`);
