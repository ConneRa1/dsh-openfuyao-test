/**
 * Panel bundle smoke test.
 *
 * `client.js` is a browser bundle with no build step, so nothing else in the
 * pipeline would notice if it stopped loading into `window.__ModuleLoader__`.
 * This drives the real factory with a stub React and asserts the loader
 * contract and the two locale dictionaries stay in step.
 */

import assert from 'node:assert/strict';
import { test } from 'node:test';

/** Any hook the components use at render time; only `apply` runs here. */
const React = new Proxy({}, {
  get: (_target, key) => {
    switch (key) {
      case 'createElement':
        return () => ({});
      case 'useState':
        return (initial) => [typeof initial === 'function' ? initial() : initial, () => {}];
      case 'useRef':
        return (initial) => ({ current: initial });
      case 'useMemo':
        return (factory) => factory();
      case 'useCallback':
        return (fn) => fn;
      case 'forwardRef':
        return (fn) => fn;
      default:
        return () => {};
    }
  },
});

test('the panel bundle registers one sidebar tab with symmetric locales', async () => {
  let definition;
  globalThis.window = {
    __ModuleLoader__: { load: (value) => { definition = value; } },
  };

  try {
    await import('../panel/client.js');
  } finally {
    delete globalThis.window;
  }

  assert.ok(definition, 'the bundle must register through window.__ModuleLoader__');
  assert.equal(definition.id, '@connera1/dsh-openfuyao-panel-test');

  const factoryResult = definition.factory((name) => {
    if (name === 'react') return React;
    throw new Error(`unexpected require(${name})`);
  });
  assert.deepEqual(factoryResult.inject, ['betterSidebar', 'locale']);

  const tabs = [];
  const dictionaries = new Map();
  const ctx = {
    effect: (factory) => factory(),
    locale: {
      register: (_namespace, locale, dictionary) => {
        dictionaries.set(locale, dictionary);
        return () => {};
      },
      // `text()` treats "value === key" as "no translation", so resolve from
      // the registered English dictionary and fall through to the key.
      bind: (namespace) => (key) => (dictionaries.get('en') ?? {})[key] ?? key,
    },
    betterSidebar: {
      registerTab: (tab) => {
        tabs.push(tab);
        return () => {};
      },
    },
  };

  factoryResult.apply(ctx);

  assert.equal(tabs.length, 1, 'exactly one tab is registered');
  assert.equal(tabs[0].id, 'openfuyao:overview');
  assert.equal(typeof tabs[0].component, 'function');
  assert.equal(typeof tabs[0].title(), 'string');

  const en = Object.keys(dictionaries.get('en') ?? {}).sort();
  const zh = Object.keys(dictionaries.get('zh') ?? {}).sort();
  assert.ok(en.length > 0, 'the English dictionary must be registered');
  assert.deepEqual(zh, en, 'EN and ZH must define the same keys');
});
