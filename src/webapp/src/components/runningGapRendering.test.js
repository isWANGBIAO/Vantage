import assert from 'node:assert/strict';
import test from 'node:test';
import * as echarts from 'echarts';

test('ECharts heart-rate contract renders null samples as separate SVG segments', () => {
  const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: 600, height: 300 });
  try {
    chart.setOption({
      xAxis: { type: 'category', data: ['2026-01-01', '2026-01-02', '2026-01-03'] },
      yAxis: {},
      series: [{ type: 'line', showSymbol: false, lineStyle: { color: 'red' }, data: [140, null, 150], connectNulls: false }],
    });
    const line = chart.renderToSVGString().match(/<path[^>]+>/g).find(path => path.includes('stroke="red"'));
    assert(line);
    const data = line.match(/d="([^"]+)"/)[1];
    assert.equal((data.match(/M/g) || []).length, 2);
    assert.equal(data.includes('L'), false);
  } finally {
    chart.dispose();
  }
});
