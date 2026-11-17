import { createElement, useContext, useMemo } from 'react';
import { FontFamilyContext, withChartFont } from './fontFamily.js';
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
  const { main } = useContext(FontFamilyContext);
  const option = useMemo(() => withChartFont(props.option, main), [props.option, main]);
  return createElement(ReactEChartsCore, {
    echarts,
    ...props,
    option,
  });
}
