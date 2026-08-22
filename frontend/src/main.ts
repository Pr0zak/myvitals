import { createApp } from "vue";
import { startDisplayPrefsSync } from "@/displayPrefs";
import { createPinia } from "pinia";
import { createRouter, createWebHistory } from "vue-router";

import "./theme";    // side-effect: applies theme on startup
import { isNeon } from "./theme";
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
    { path: "/rings", name: "rings", component: () => import("./views/Rings.vue") },
    { path: "/body", name: "body", component: () => import("./views/Body.vue") },
    { path: "/train", name: "train", component: () => import("./views/Train.vue") },
    { path: "/coach-hub", name: "coach-hub", component: () => import("./views/CoachHub.vue") },
    { path: "/you", name: "you", component: () => import("./views/You.vue") },
    { path: "/trends", name: "trends", component: () => import("./views/Trends.vue") },
    // DAY-1: the day is in the URL so a particular day is linkable and
    // survives a reload. `/day` with no param resolves to today in the view.
    { path: "/day/:date?", name: "day", component: () => import("./views/Day.vue") },
    { path: "/sleep", name: "sleep", component: () => import("./views/Sleep.vue") },
    { path: "/heart-rate", name: "heart-rate", component: () => import("./views/HeartRate.vue") },
    { path: "/weight", name: "weight", component: () => import("./views/Weight.vue") },
    { path: "/steps", name: "steps", component: () => import("./views/Steps.vue") },
    { path: "/hrv", name: "hrv", component: () => import("./views/Hrv.vue") },
    { path: "/skin-temp", name: "skin-temp", component: () => import("./views/SkinTemp.vue") },
    { path: "/blood-pressure", name: "blood-pressure", component: () => import("./views/BloodPressure.vue") },
    { path: "/measurements", name: "measurements", component: () => import("./views/Measurements.vue") },
    { path: "/journal", name: "journal", component: () => import("./views/Journal.vue") },
    { path: "/sober", name: "sober", component: () => import("./views/Sober.vue") },
    { path: "/fasting", name: "fasting", component: () => import("./views/Fasting.vue") },
    { path: "/watch", name: "watch", component: () => import("./views/Watch.vue") },
    { path: "/coach", name: "coach", component: () => import("./views/Coach.vue") },
    { path: "/goals", name: "goals", component: () => import("./views/Goals.vue") },
    { path: "/meals/recipes", name: "meals-recipes", component: () => import("./views/meals/Recipes.vue") },
    { path: "/meals/pantry", name: "meals-pantry", component: () => import("./views/meals/Pantry.vue") },
    { path: "/meals/foods", name: "meals-foods", component: () => import("./views/meals/Foods.vue") },
    { path: "/meals/plan", name: "meals-plan", component: () => import("./views/meals/Plan.vue") },
    { path: "/meals/shopping", name: "meals-shopping", component: () => import("./views/meals/Shopping.vue") },
    { path: "/meals/ideas", name: "meals-ideas", component: () => import("./views/meals/Suggest.vue") },
    { path: "/meals/nutrition", name: "meals-nutrition", component: () => import("./views/meals/Nutrition.vue") },
    { path: "/activities", name: "activities", component: () => import("./views/Activities.vue") },
    { path: "/activity/:source/:id", name: "activity-detail", component: () => import("./views/ActivityDetail.vue") },
    { path: "/activities/map", name: "activities-map", component: () => import("./views/ActivitiesMap.vue") },
    { path: "/activities/compare", name: "activities-compare", component: () => import("./views/ActivitiesCompare.vue") },
    { path: "/calendar", name: "calendar", component: () => import("./views/Calendar.vue") },
    { path: "/analytics", name: "analytics", component: () => import("./views/Analytics.vue") },
    { path: "/insights", name: "insights", component: () => import("./views/Insights.vue") },
    { path: "/compare", name: "compare", component: () => import("./views/Compare.vue") },
    { path: "/trails", name: "trails", component: () => import("./views/Trails.vue") },
    { path: "/trails/map", name: "trails-map", component: () => import("./views/TrailsMap.vue") },
    { path: "/trails/:id/visits", name: "trail-visits", component: () => import("./views/TrailVisits.vue") },
    { path: "/workout/strength/today", name: "workout-strength-today", component: () => import("./views/workout/StrengthToday.vue") },
    { path: "/workout/strength/catalog", name: "workout-strength-catalog", component: () => import("./views/workout/StrengthCatalog.vue") },
    { path: "/workout/strength/history", name: "workout-strength-history", component: () => import("./views/workout/StrengthHistory.vue") },
    { path: "/workout/strength/equipment", name: "workout-strength-equipment", component: () => import("./views/workout/StrengthEquipment.vue") },
    { path: "/workout/strength/charts", name: "workout-strength-charts", component: () => import("./views/workout/StrengthCharts.vue") },
    { path: "/workout/strength/day/:date", name: "workout-strength-day", component: () => import("./views/workout/StrengthDayView.vue") },
    { path: "/logs", name: "logs", component: () => import("./views/Logs.vue") },
    { path: "/settings", name: "settings", component: () => import("./views/Settings.vue") },
    // Catch-all: unknown paths (incl. a stale bundle that predates a new route)
    // redirect home instead of rendering a blank page.
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

// In the Vitality Neon shell the home is the Rings screen, not the classic
// Today dashboard. (Classic themes keep "/" → Today.)
router.beforeEach((to) => {
  if (to.path === "/" && isNeon.value) return "/rings";
});

createApp(App).use(createPinia()).use(router).mount("#app");

// DISP-1: reconcile locally cached display preferences against the
// server's. Fires after mount on purpose — the first paint uses the
// localStorage values so the theme does not flash and distances do not
// render in the wrong unit while a round-trip completes.
startDisplayPrefsSync();
