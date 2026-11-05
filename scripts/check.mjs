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

const data = JSON.parse(readFileSync('data.example.json', 'utf8'));
assert.equal(data.balance, '0.00');
assert.equal(data.cashback, '0');
assert.deepEqual(data.cards, [], 'Published data must not contain real cards');
assert.deepEqual(data.txns, [], 'Published data must not contain real transactions');
assert.deepEqual(data.statement, {}, 'Published data must not contain account details');
assert.deepEqual(data.meta, {});

console.log(`Validated ${scripts.length} inline script(s) and empty deployment data.`);
