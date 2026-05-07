/**
 * Leaflet's default marker icon URLs (`leaflet/dist/images/marker-icon.png`,
 * etc.) are resolved at runtime against the page origin, which doesn't work
 * when Leaflet is bundled via Vite — the assets aren't at the assumed path,
 * so markers render as broken-image placeholders.
 *
 * Importing the PNGs explicitly turns them into hashed, served URLs that
 * Vite handles correctly. mergeOptions() points L.Icon.Default at those
 * URLs so every L.marker(...) call without a custom icon Just Works.
 *
 * Import this module from anywhere that uses default markers (TrailMap,
 * Trails edit drawer, ActivityDetail, …). Multiple imports are no-ops
 * because Vite caches the side-effect.
 */
import L from "leaflet";
import iconUrl from "leaflet/dist/images/marker-icon.png";
import iconRetinaUrl from "leaflet/dist/images/marker-icon-2x.png";
import shadowUrl from "leaflet/dist/images/marker-shadow.png";

L.Icon.Default.mergeOptions({
  iconUrl,
  iconRetinaUrl,
  shadowUrl,
});
