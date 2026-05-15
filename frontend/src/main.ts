import { createApp } from "vue";
import { createPinia } from "pinia";
import { createRouter, createWebHistory } from "vue-router";

import "./echarts";  // side-effect: registers ECharts modules
import "./theme";    // side-effect: applies theme on startup
import App from "./App.vue";

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior(to, _from, savedPosition) {
    if (to.hash) {
      // Wait for the target view's data + charts to mount before scrolling
      // (most page Cards render after an async load).
      return new Promise((resolve) => {
        setTimeout(() => resolve({ el: to.hash, behavior: "smooth", top: 16 }), 250);
      });
    }
    if (savedPosition) return savedPosition;
    return { top: 0 };
  },
  routes: [
    { path: "/", name: "today", component: () => import("./views/Today.vue") },
    { path: "/trends", name: "trends", component: () => import("./views/Trends.vue") },
    { path: "/sleep", name: "sleep", component: () => import("./views/Sleep.vue") },
    { path: "/heart-rate", name: "heart-rate", component: () => import("./views/HeartRate.vue") },
    { path: "/yoga-icon-samples", name: "yoga-icon-samples", component: () => import("./views/YogaIconSamples.vue") },
    { path: "/weight", name: "weight", component: () => import("./views/Weight.vue") },
    { path: "/blood-pressure", name: "blood-pressure", component: () => import("./views/BloodPressure.vue") },
    { path: "/journal", name: "journal", component: () => import("./views/Journal.vue") },
    { path: "/sober", name: "sober", component: () => import("./views/Sober.vue") },
    { path: "/fasting", name: "fasting", component: () => import("./views/Fasting.vue") },
    { path: "/watch", name: "watch", component: () => import("./views/Watch.vue") },
    { path: "/coach", name: "coach", component: () => import("./views/Coach.vue") },
    { path: "/goals", name: "goals", component: () => import("./views/Goals.vue") },
    { path: "/activities", name: "activities", component: () => import("./views/Activities.vue") },
    { path: "/activity/:source/:id", name: "activity-detail", component: () => import("./views/ActivityDetail.vue") },
    { path: "/activities/map", name: "activities-map", component: () => import("./views/ActivitiesMap.vue") },
    { path: "/activities/compare", name: "activities-compare", component: () => import("./views/ActivitiesCompare.vue") },
    { path: "/calendar", name: "calendar", component: () => import("./views/Calendar.vue") },
    { path: "/insights", name: "insights", component: () => import("./views/Insights.vue") },
    { path: "/compare", name: "compare", component: () => import("./views/Compare.vue") },
    { path: "/trails", name: "trails", component: () => import("./views/Trails.vue") },
    { path: "/trails/map", name: "trails-map", component: () => import("./views/TrailsMap.vue") },
    { path: "/workout/strength/today", name: "workout-strength-today", component: () => import("./views/workout/StrengthToday.vue") },
    { path: "/workout/strength/catalog", name: "workout-strength-catalog", component: () => import("./views/workout/StrengthCatalog.vue") },
    { path: "/workout/strength/history", name: "workout-strength-history", component: () => import("./views/workout/StrengthHistory.vue") },
    { path: "/workout/strength/equipment", name: "workout-strength-equipment", component: () => import("./views/workout/StrengthEquipment.vue") },
    { path: "/workout/strength/charts", name: "workout-strength-charts", component: () => import("./views/workout/StrengthCharts.vue") },
    { path: "/workout/strength/day/:date", name: "workout-strength-day", component: () => import("./views/workout/StrengthDayView.vue") },
    { path: "/logs", name: "logs", component: () => import("./views/Logs.vue") },
    { path: "/settings", name: "settings", component: () => import("./views/Settings.vue") },
  ],
});

createApp(App).use(createPinia()).use(router).mount("#app");
