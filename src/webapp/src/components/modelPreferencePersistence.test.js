import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { findModelOption, persistPreferredModelOption } from '../utils/llmModelCatalog.js';

for (const [component, name, next] of [
  ['ActionPlan', 'handleModelChange', 'handleFastModeChange'],
  ['ChatInterface', 'handleModelChange', 'handleFastModeChange'],
  ['ExpenseSheet', 'handlePurchaseModelChange', 'handlePurchaseReasoningEffortChange'],
]) {
  for (const fails of [false, true]) {
    test(`${component} ${fails ? 'retains prior model on save failure' : 'publishes selection only after successful canonical save'}`, async () => {
      const source = readFileSync(new URL(`./${component}.jsx`, import.meta.url), 'utf8');
      const handler = source.slice(source.indexOf(`const ${name} =`), source.indexOf(`const ${next} =`));
      let current = 'glm::glm';
      let pending = false;
      let error = '';
      const events = [];
      let finish;
      const request = new Promise((resolve, reject) => { finish = () => fails ? reject(new Error('synthetic save failure')) : resolve({}); });
      const sandbox = {
        findModelOption, persistPreferredModelOption, availableModels: [{ id: 'ds::deepseek', model: 'deepseek', provider_route: 'ds' }],
        fetchBackendJson: () => request, setSelectedModel: (id) => { current = id; },
        modelPreferenceSavingRef: { current: false }, setModelPreferenceSaving: (value) => { pending = value; },
        manualModelSelectionRef: { current: false }, redactSensitiveText: (value) => value,
        setAutoRefreshStatus: (value) => { error = value; }, setChatError: (value) => { error = value; }, setPurchaseError: (value) => { error = value; },
        useCallback: (fn) => fn, window: { dispatchEvent: (event) => events.push(event) },
        CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init.detail; } },
      };
      vm.runInNewContext(`${handler}; globalThis.handle = ${name};`, sandbox);
      const operation = sandbox.handle({ target: { value: 'ds::deepseek' } });
      assert.equal(current, 'glm::glm');
      assert.equal(pending, true);
      finish();
      await operation;
      assert.equal(current, fails ? 'glm::glm' : 'ds::deepseek');
      assert.equal(pending, false);
      assert.equal(events.length, fails ? 0 : 1);
      if (fails) assert.match(error, /synthetic save failure/);
    });
  }
}
