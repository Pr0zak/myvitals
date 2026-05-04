import { createApp } from "vue";
import { createPinia } from "pinia";
import { createRouter, createWebHistory } from "vue-router";

import "./echarts";  // side-effect: registers ECharts modules
import "./theme";    // side-effect: applies theme on startup
import App from "./App.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "today", component: () => import("./views/Today.vue") },
    { path: "/trends", name: "trends", component: () => import("./views/Trends.vue") },
    { path: "/sleep", name: "sleep", component: () => import("./views/Sleep.vue") },
    { path: "/log", name: "log", component: () => import("./views/Log.vue") },
    { path: "/activities", name: "activities", component: () => import("./views/Activities.vue") },
    { path: "/activity/:source/:id", name: "activity-detail", component: () => import("./views/ActivityDetail.vue") },
    { path: "/activities/map", name: "activities-map", component: () => import("./views/ActivitiesMap.vue") },
    { path: "/calendar", name: "calendar", component: () => import("./views/Calendar.vue") },
    { path: "/insights", name: "insights", component: () => import("./views/Insights.vue") },
    { path: "/compare", name: "compare", component: () => import("./views/Compare.vue") },
    { path: "/alerts", name: "alerts", component: () => import("./views/Alerts.vue") },
    { path: "/logs", name: "logs", component: () => import("./views/Logs.vue") },
    { path: "/settings", name: "settings", component: () => import("./views/Settings.vue") },
  ],
});

createApp(App).use(createPinia()).use(router).mount("#app");
