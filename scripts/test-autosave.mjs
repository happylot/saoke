import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const html = readFileSync('index.html', 'utf8');
const source = html.slice(html.indexOf('/* ---------- data ---------- */'), html.indexOf('let F ='));
const nodes = new Map();
const requests = [];
const context = vm.createContext({
  console, setTimeout: () => 1, clearTimeout: () => {},
  $: selector => {
    if (!nodes.has(selector)) nodes.set(selector, {style:{}});
    return nodes.get(selector);
  },
  uid: () => 'test', render: () => {}, toast: () => {},
  fetch: (url, options) => new Promise((resolve, reject) => requests.push({url, options, resolve, reject})),
});
vm.runInContext(source, context);
const run = code => vm.runInContext(code, context);
const respond = (request, status, body) => request.resolve({ok:status===200, status, json:async()=>body});
run('loading=false; loaded=true; lastSaved=snap(); S.balance="1"; save()');
const first = run('flush()');
assert.equal(requests.length,1);
assert.equal(JSON.parse(requests[0].options.body).data.balance,'1');
run('S.balance="2"; save(); flush()');
assert.equal(requests.length,1,'Concurrent saves must be serialized');
respond(requests[0],200,{revision:1});
await first;
assert.equal(run('dirty'),true,'Edits during a save must remain pending');
const second=run('flush()');
assert.equal(JSON.parse(requests[1].options.body).revision,1);
assert.equal(JSON.parse(requests[1].options.body).data.balance,'2');
respond(requests[1],200,{revision:2});
await second;
assert.equal(run('dirty'),false);

run('S.balance="3"; save()');
const offline=run('flush()');
requests[2].reject(new Error('offline'));
await offline;
assert.equal(run('dirty'),true,'Failed saves must preserve local edits');
assert.equal(run('S.balance'),'3');
const retry=run('flush()');
respond(requests[3],200,{revision:3});
await retry;
assert.equal(run('dirty'),false);

run('S.balance="4"; save()');
const conflict=run('flush()');
respond(requests[4],409,{error:'conflict'});
await conflict;
assert.equal(run('conflict'),true);
assert.equal(run('dirty'),true);
assert.equal(run('S.balance'),'4');
await run('flush()');
assert.equal(requests.length,5,'Conflicts must not overwrite another browser');
console.log('Autosave serialization, pending edits, network retry and conflict checks passed.');
