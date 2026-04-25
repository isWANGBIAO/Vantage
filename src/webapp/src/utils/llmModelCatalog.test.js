import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildModelOptionsFromCatalog,
  findModelOption,
} from './llmModelCatalog.js';

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
