// Regression test for the show-more / show-less behaviour in base.html.
//
// Extracts the real <script> from templates/base.html and runs it against a
// minimal fake DOM, so this tests the code that actually ships rather than a
// copy of it. Run with:  node test_showmore.js
const fs = require('fs');
const path = require('path');

const template = fs.readFileSync(path.join(__dirname, 'templates', 'base.html'), 'utf8');
const start = template.indexOf('(function () {\n        var STORE');
const end = template.indexOf('</script>', start);
if (start < 0 || end < 0) {
  console.error('FAIL: could not locate the show-more script in templates/base.html');
  process.exit(1);
}
const source = template.slice(start, end);

// --- minimal DOM -----------------------------------------------------------
function makeEl(tag, attrs) {
  return {
    tagName: tag.toUpperCase(),
    attrs: attrs || {},
    style: {},
    children: [],
    parent: null,
    _listeners: {},
    nodeType: 1,
    textContent: '',
    hasAttribute(k) { return k in this.attrs; },
    getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k]; },
    setAttribute(k, v) { this.attrs[k] = v; },
    appendChild(c) { c.parent = this; this.children.push(c); },
    insertBefore(node, ref) {
      node.parent = this;
      const i = ref ? this.children.indexOf(ref) : -1;
      if (i < 0) { this.children.push(node); } else { this.children.splice(i, 0, node); }
      return node;
    },
    get parentNode() { return this.parent; },
    addEventListener(ev, fn) { this._listeners[ev] = fn; },
    click() { if (this._listeners.click) this._listeners.click(); },
    closest(t) {
      let n = this.parent;
      while (n) { if (n.tagName === t.toUpperCase()) return n; n = n.parent; }
      return null;
    },
  };
}

const store = {};
global.window = {
  localStorage: {
    getItem: k => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = v; },
  },
};
global.document = {
  readyState: 'complete',
  addEventListener() {},
  createElement: t => makeEl(t),
  querySelectorAll: () => global.__containers,
};

function run(containers) {
  global.__containers = containers;
  store['oweru.showmore'] = '{}';
  eval(source);
}

function rows(parent, n, tag) {
  for (let i = 0; i < n; i++) parent.children.push(makeEl(tag || 'tr'));
}
const visible = c => c.children.filter(x => x.style.display !== 'none').length;

let fails = 0;
function check(label, cond, extra) {
  console.log((cond ? '  PASS  ' : '  FAIL  ') + label + (extra ? '  [' + extra + ']' : ''));
  if (!cond) fails++;
}

// A table nested in a page, mirroring real markup.
function tableWith(rowsN, attrs) {
  const page = makeEl('div');
  const table = makeEl('table');
  page.appendChild(table);
  const tbody = makeEl('tbody', attrs);
  table.appendChild(tbody);
  rows(tbody, rowsN);
  return { page, table, tbody };
}

console.log('long table (12 rows, limit 5)');
{
  const { page, table, tbody } = tableWith(12, { 'data-showmore': '5', 'data-key': 't1' });
  run([tbody]);
  const btn = page.children[1];
  check('button sits after the table, not inside tbody',
        page.children.length === 2 && btn && btn.tagName === 'BUTTON' && table.children.length === 1);
  check('button counts the hidden rows', btn.textContent === 'Show 7 more', btn.textContent);
  check('5 rows visible when collapsed', visible(tbody) === 5, 'visible=' + visible(tbody));
  btn.click();
  check('all rows visible after Show more', visible(tbody) === 12, 'visible=' + visible(tbody));
  check('button flips to Show less', btn.textContent === 'Show less', btn.textContent);
  check('aria-expanded is true', btn.getAttribute('aria-expanded') === 'true');
  btn.click();
  check('collapses again', visible(tbody) === 5);
}

console.log('short list is left alone');
{
  const holder = makeEl('div');
  rows(holder, 3, 'li');
  run([holder]);
  check('no button added when under the limit',
        holder.children.filter(c => c.tagName === 'BUTTON').length === 0);
}

console.log('non-table container');
{
  const host = makeEl('div');
  const list = makeEl('ul', { 'data-showmore': '5' });
  host.appendChild(list);
  rows(list, 8, 'li');
  run([list]);
  check('button appended after a plain ul',
        host.children.length === 2 && host.children[1].tagName === 'BUTTON' &&
        list.children.filter(c => c.tagName === 'BUTTON').length === 0);
}

console.log('state remembered between visits');
{
  const a = tableWith(12, { 'data-showmore': '5', 'data-key': 'sticky' });
  run([a.tbody]);
  a.page.children[1].click();
  const saved = JSON.parse(store['oweru.showmore']);
  check('expansion written to storage', saved.sticky === true, JSON.stringify(saved));

  store['oweru.showmore'] = JSON.stringify(saved);
  const b = tableWith(12, { 'data-showmore': '5', 'data-key': 'sticky' });
  global.__containers = [b.tbody];
  eval(source);
  check('stays expanded on revisit', visible(b.tbody) === 12, 'visible=' + visible(b.tbody));
}

console.log('two lists on one page stay independent');
{
  const a = tableWith(10, { 'data-showmore': '5', 'data-key': 'k-a' });
  const b = tableWith(10, { 'data-showmore': '5', 'data-key': 'k-b' });
  run([a.tbody, b.tbody]);
  a.page.children[1].click();
  check('expanding one does not expand the other', visible(b.tbody) === 5,
        'b visible=' + visible(b.tbody));
}

console.log(fails ? '\n' + fails + ' FAILED' : '\nall checks passed');
process.exit(fails ? 1 : 0);
