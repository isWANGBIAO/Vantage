import { createElement } from 'react';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  ToolboxComponent,
  DataZoomComponent,
  RadarComponent,
} from 'echarts/components';
import {
  LineChart,
  BarChart,
  ScatterChart,
  RadarChart,
} from 'echarts/charts';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  GridComponent,
  TooltipComponent,
  LegendComponent,
  ToolboxComponent,
  DataZoomComponent,
  RadarComponent,
  LineChart,
  BarChart,
  ScatterChart,
  RadarChart,
  CanvasRenderer,
]);

export { echarts };

export default function ReactECharts(props) {
  return createElement(ReactEChartsCore, {
    echarts,
    ...props,
  });
}
