// Centralised ECharts module registration. Imported once from main.ts so all
// chart components can use VChart without each one re-registering.
import { use } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { BarChart, GaugeChart, LineChart, PieChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
} from "echarts/components";

use([
  CanvasRenderer,
  LineChart,
  BarChart,
  GaugeChart,
  PieChart,
  GridComponent,
  TooltipComponent,
  TitleComponent,
  LegendComponent,
  DataZoomComponent,
]);
