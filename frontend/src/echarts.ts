// Centralised ECharts module registration + VChart re-export.
//
// Previously this was a side-effect `import "./echarts"` in main.ts, which
// pulled all of ECharts (~600 KB) into the main entry chunk — every route paid
// for it, including chartless ones (Settings, Logs, Journal, Goals). Now it's a
// barrel: chart views `import VChart from "@/echarts"`, so ECharts is only
// fetched when a chart-bearing (lazy) route actually loads. Importing this
// module runs `use([...])` before VChart is handed out, so registration is
// always in place by first render.
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
import VChart from "vue-echarts";

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

export default VChart;
