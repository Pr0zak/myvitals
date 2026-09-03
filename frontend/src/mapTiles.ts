/**
 * One definition of the basemap — MAP-1.
 *
 * CARTO began stamping "API KEY REQUIRED" diagonally across every tile at
 * `basemaps.cartocdn.com`. The tiles still return HTTP 200, so nothing errored
 * and nothing logged; the watermark simply appeared on all eight maps in the
 * app at once. That is why this moved into one module: the URL was written out
 * longhand at four places on the web and four more inside the phone's
 * Leaflet-in-a-WebView HTML, so a provider change meant eight edits and eight
 * chances to leave one behind.
 *
 * Esri's gray canvas replaces it. It needs no key and no account, which is the
 * point — a key would have to live in settings and be plumbed to eight
 * surfaces, and it must never be committed to a public repo. It is also built
 * for exactly this job: a desaturated backdrop that a route line reads clearly
 * against, which is what CARTO's Positron and Dark Matter were chosen for.
 *
 * Three things about Esri's scheme that are easy to get wrong:
 *
 * **The axis order is `{z}/{y}/{x}`.** Leaflet's default is `{z}/{x}/{y}`, so
 * a straight URL swap silently serves the wrong tile — mirrored geography, no
 * error.
 *
 * **Labels are a separate service.** `..._Base` carries no place names at all;
 * `..._Reference` supplies them and is added over the top.
 *
 * **The ceiling is zoom 16.** Above it the service returns a grey placeholder
 * reading "Map data not yet available" — with a 200 status, so Leaflet treats
 * it as a good tile and paints it. `maxNativeZoom` makes Leaflet upscale zoom
 * 16 instead, which matters on the trail maps, where zooming in is the point.
 */

const ESRI = "https://services.arcgisonline.com/ArcGIS/rest/services/Canvas";

/** Zoom 17+ serves a "Map data not yet available" placeholder, at HTTP 200. */
export const MAP_MAX_NATIVE_ZOOM = 16;
export const MAP_MAX_ZOOM = 19;
export const MAP_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>, Tiles &copy; Esri';

/** The backdrop. Carries no labels — pair it with `labelTileUrl`. */
export function baseTileUrl(dark: boolean): string {
  const style = dark ? "World_Dark_Gray_Base" : "World_Light_Gray_Base";
  return `${ESRI}/${style}/MapServer/tile/{z}/{y}/{x}`;
}

/** Place names, drawn over the base and over the route lines' pane. */
export function labelTileUrl(dark: boolean): string {
  const style = dark ? "World_Dark_Gray_Reference" : "World_Light_Gray_Reference";
  return `${ESRI}/${style}/MapServer/tile/{z}/{y}/{x}`;
}

/** The options every basemap layer takes. Spread rather than copied, so the
 *  zoom ceiling cannot be remembered at three sites and forgotten at a
 *  fourth. */
export function tileOptions(): {
  attribution: string; maxZoom: number; maxNativeZoom: number;
} {
  return {
    attribution: MAP_ATTRIBUTION,
    maxZoom: MAP_MAX_ZOOM,
    maxNativeZoom: MAP_MAX_NATIVE_ZOOM,
  };
}
