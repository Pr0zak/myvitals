"""One basemap definition, and it needs no key — MAP-1.

Reported from live use: every map in the app started showing "API KEY
REQUIRED" stamped diagonally across it. CARTO began watermarking
`basemaps.cartocdn.com`, and the tiles still return HTTP 200 — so nothing
errored, nothing logged, and all ten maps degraded at once with no signal
anywhere except the pixels.

Ten, not the four an obvious grep finds. The URL was written longhand at six
places on the web and four more inside the phone's Leaflet-in-a-WebView HTML,
where it is a string in a Kotlin file and invisible to the frontend
toolchain. Two of the web copies were missed on the first pass precisely
because they assembled the URL into a local before use. That is the argument
for `frontend/src/mapTiles.ts`: a provider change should be one edit, not ten
chances to leave one behind.

Esri's gray canvas replaces it. Keyless is the requirement, not a bonus: a key
lives in the tile URL, so it would need plumbing to ten surfaces and must
never reach a public repo.

THREE THINGS ABOUT ESRI THAT FAIL SILENTLY IF MISSED, all pinned below.

The axis order is `{z}/{y}/{x}`. Leaflet's default is `{z}/{x}/{y}`, so a
straight swap serves mirrored geography with no error at all.

Labels are a separate service. `..._Base` carries no place names, so a
one-layer swap yields a map with no towns on it.

The ceiling is zoom 16. Above it the service returns a grey placeholder
reading "Map data not yet available" — at HTTP 200, so Leaflet treats it as a
real tile and paints it over the map. `maxNativeZoom` makes Leaflet upscale
instead. This matters most on the trail maps, where zooming in is the point.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
WEB = REPO / "frontend" / "src"
PHONE = REPO / "android" / "app" / "src" / "main" / "kotlin" / "app" / "myvitals"
MODULE = WEB / "mapTiles.ts"


def _sources() -> list[pathlib.Path]:
    out = [p for p in WEB.rglob("*") if p.suffix in (".vue", ".ts")]
    out += list(PHONE.rglob("*.kt"))
    return out


def _tile_layer_files() -> list[pathlib.Path]:
    return [p for p in _sources() if "L.tileLayer(" in p.read_text()]


class TestNoProviderNeedsAKey:
    def test_carto_is_gone_everywhere(self):
        """It still returns 200, so only the pixels ever said anything."""
        bad = [
            str(p.relative_to(REPO)) for p in _sources()
            if "cartocdn.com" in p.read_text() and p != MODULE
        ]
        assert not bad, bad

    def test_no_map_url_carries_a_key_parameter(self):
        """A key in a tile URL is a secret in a public repo."""
        for p in _sources():
            for m in re.findall(r"https://[^\s'\"`)]+", p.read_text()):
                if "MapServer/tile" not in m and "{z}" not in m:
                    continue
                low = m.lower()
                assert "api_key" not in low and "apikey" not in low, m
                assert "access_token" not in low, m


class TestTheEsriSchemeIsUsedCorrectly:
    def test_every_tile_url_puts_y_before_x(self):
        """Leaflet's default is {z}/{x}/{y}; Esri is {z}/{y}/{x}. Getting it
        backwards serves the wrong tile silently."""
        for p in _sources():
            for url in re.findall(r"MapServer/tile/[^'\"`\s]*", p.read_text()):
                assert url.endswith("{z}/{y}/{x}"), f"{p.name}: {url}"

    def test_every_map_also_adds_the_label_layer(self):
        """Esri's base carries no place names at all."""
        for p in _tile_layer_files():
            src = p.read_text()
            n_base = src.count("_Base/MapServer") + src.count("baseTileUrl(")
            n_ref = src.count("_Reference/MapServer") + src.count("labelTileUrl(")
            assert n_base == n_ref, f"{p.name}: {n_base} base vs {n_ref} label"

    def test_every_layer_caps_the_native_zoom(self):
        """Zoom 17+ returns a grey "Map data not yet available" placeholder
        AT HTTP 200, so without this Leaflet paints it as a real tile."""
        for p in _tile_layer_files():
            src = p.read_text()
            assert "maxNativeZoom" in src or "tileOptions()" in src, p.name

    def test_the_cap_is_sixteen(self):
        src = MODULE.read_text()
        assert "MAP_MAX_NATIVE_ZOOM = 16" in src

    def test_no_subdomain_placeholder_survives(self):
        """Esri serves from one host; a leftover {s} yields a dead hostname."""
        for p in _tile_layer_files():
            for url in re.findall(r"https://[^\s'\"`)]*\{z\}[^\s'\"`)]*",
                                  p.read_text()):
                assert "{s}" not in url, f"{p.name}: {url}"


class TestOneDefinition:
    def test_the_web_reads_the_shared_module(self):
        """Six copies is why two of them were missed on the first pass."""
        for p in WEB.rglob("*.vue"):
            src = p.read_text()
            if "L.tileLayer(" not in src:
                continue
            assert "@/mapTiles" in src, p.name

    def test_no_web_view_writes_a_tile_host_itself(self):
        for p in WEB.rglob("*.vue"):
            assert "arcgisonline.com" not in p.read_text(), p.name

    def test_the_phone_is_the_known_exception(self):
        """Its maps are Leaflet inside a WebView, so the URL is a string in
        Kotlin and cannot import the module. Listed explicitly so the count
        is a decision rather than a drift."""
        phone = sorted(
            p.name for p in PHONE.rglob("*.kt")
            if "arcgisonline.com" in p.read_text()
        )
        assert phone == [
            "ActivityDetailScreen.kt", "ActivityMapScreen.kt", "TrailsScreen.kt",
        ], phone

    def test_attribution_is_present_on_every_map(self):
        """Esri's terms require it, and OSM's do for the underlying data."""
        for p in _tile_layer_files():
            src = p.read_text()
            assert "attribution" in src or "tileOptions()" in src, p.name
