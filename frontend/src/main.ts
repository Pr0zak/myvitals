import { createApp } from "vue";
import { createPinia } from "pinia";
import { createRouter, createWebHistory } from "vue-router";

import "./echarts";  // side-effect: registers ECharts modules
import App from "./App.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "today", component: () => import("./views/Today.vue") },
    { path: "/trends", name: "trends", component: () => import("./views/Trends.vue") },
    { path: "/sleep", name: "sleep", component: () => import("./views/Sleep.vue") },
    { path: "/log", name: "log", component: () => import("./views/Log.vue") },
    { path: "/logs", name: "logs", component: () => import("./views/Logs.vue") },
    { path: "/settings", name: "settings", component: () => import("./views/Settings.vue") },
  ],
});

createApp(App).use(createPinia()).use(router).mount("#app");
