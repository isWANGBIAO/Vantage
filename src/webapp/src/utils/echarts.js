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
  MarkLineComponent,
} from 'echarts/components';
import {
  LineChart,
  BarChart,
  ScatterChart,
  RadarChart,
  CustomChart,
} from 'echarts/charts';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  GridComponent,
  TooltipComponent,
  LegendComponent,
  ToolboxComponent,
  DataZoomComponent,
  RadarComponent,
  MarkLineComponent,
  LineChart,
  BarChart,
  ScatterChart,
  RadarChart,
  CustomChart,
  CanvasRenderer,
]);

export { echarts };

export default function ReactECharts(props) {
  return createElement(ReactEChartsCore, {
    echarts,
    ...props,
  });
}
