// Centralised ECharts module registration. Imported once from main.ts so all
// chart components can use VChart without each one re-registering.
import { use } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { BarChart, GaugeChart, HeatmapChart, LineChart, PieChart, RadarChart, ScatterChart } from "echarts/charts";
import {
  CalendarComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  RadarComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";

use([
  CanvasRenderer,
  LineChart,
  BarChart,
  GaugeChart,
  PieChart,
  HeatmapChart,
  ScatterChart,
  RadarChart,
  GridComponent,
  TooltipComponent,
  TitleComponent,
  LegendComponent,
  DataZoomComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  CalendarComponent,
  VisualMapComponent,
  RadarComponent,
]);
