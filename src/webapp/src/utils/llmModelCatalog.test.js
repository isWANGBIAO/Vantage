import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildModelOptionsFromCatalog,
  findModelOption,
  resolvePreferredModelOption,
  persistPreferredModelOption,
} from './llmModelCatalog.js';

test('canonical default wins over stale browser model preference', () => {
  const options = buildModelOptionsFromCatalog({ default_model: 'deepseek', default_provider_route: 'ds',
    providers: [{ route: 'glm', models: ['glm'] }, { route: 'ds', models: ['deepseek'] }] });
  assert.equal(resolvePreferredModelOption(options, { getItem: () => 'glm::glm' }).id, 'ds::deepseek');
});

test('model preference saves only route/model before publishing success', async () => {
  const option = { id: 'ds::deepseek', provider_route: 'ds', model: 'deepseek' };
  let request;
  const result = await persistPreferredModelOption(option, async (url, init) => {
    request = { url, init }; return { provider_route: 'ds', model: 'deepseek' };
  });
  assert.equal(request.url, '/api/v1/models/preference');
  assert.equal(request.init.method, 'PUT');
  assert.deepEqual(JSON.parse(request.init.body), { provider_route: 'ds', model: 'deepseek' });
  assert.equal(result, option);
});

test('failed preference save rejects without changing the previous selection', async () => {
  let current = 'glm::glm';
  await assert.rejects(async () => {
    const saved = await persistPreferredModelOption({ id: 'ds::deepseek', provider_route: 'ds', model: 'deepseek' },
      async () => { throw new Error('save failed'); });
    current = saved.id;
  }, /save failed/);
  assert.equal(current, 'glm::glm');
});

test('buildModelOptionsFromCatalog preserves provider-aware duplicate model names', () => {
  const options = buildModelOptionsFromCatalog({
    default_model: 'gpt-5.5',
    default_provider_route: 'custom',
    model_options: [
      {
        model: 'gpt-5.5',
        provider_route: 'custom',
        provider_label: 'custom',
      },
      {
        model: 'gpt-5.5',
        provider_route: 'cloud',
        provider_label: 'cloud',
      },
    ],
  });

  assert.deepEqual(
    options.map((option) => ({
      id: option.id,
      label: option.label,
      model: option.model,
      provider_route: option.provider_route,
      is_default: option.is_default,
    })),
    [
      {
        id: 'custom::gpt-5.5',
        label: 'gpt-5.5 | custom',
        model: 'gpt-5.5',
        provider_route: 'custom',
        is_default: true,
      },
      {
        id: 'cloud::gpt-5.5',
        label: 'gpt-5.5 | cloud',
        model: 'gpt-5.5',
        provider_route: 'cloud',
        is_default: false,
      },
    ],
  );
});

test('findModelOption reads provider-aware ids and falls back to model ids', () => {
  const options = buildModelOptionsFromCatalog({
    models: ['gpt-5.4'],
  });

  assert.equal(findModelOption(options, 'gpt-5.4')?.model, 'gpt-5.4');
  assert.equal(findModelOption(options, 'missing'), null);
});
