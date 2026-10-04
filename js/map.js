// ======================================================
// สร้างแผนที่ (MapLibre GL JS) - Modern Style
// ======================================================

document.addEventListener("DOMContentLoaded", function () {

    const map = new maplibregl.Map({
        container: "map",
        style: {
            version: 8,
            sources: {
                osm: {
                    type: "raster",
                    tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
                    tileSize: 256,
                    attribution: "© OpenStreetMap Contributors"
                }
            },
            layers: [{ id: "osm", type: "raster", source: "osm" }]
        },
        center: [102.835, 16.432], 
        zoom: 9,
        minZoom: 7,
        maxZoom: 18
    });

    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }));
    window.map = map;

});

// ======================================================
// จัดการชั้นข้อมูลรายปัจจัย (Layer toggle) และ WLC
// ======================================================
function factorLayerId(factor) {
    const safe = factor.replace(/[^a-zA-Z0-9ก-๙_-]/g, "_");
    return { src: `factor-src-${safe}`, layer: `factor-layer-${safe}` };
}

function addFactorLayer(factor, imageBase64, bounds) {
    if (!window.map) return;
    const [west, south, east, north] = bounds;
    const coordinates = [[west, north], [east, north], [east, south], [west, south]];
    const dataUrl = `data:image/png;base64,${imageBase64}`;
    const { src, layer } = factorLayerId(factor);

    const applyLayer = () => {
        if (window.map.getLayer(layer)) window.map.removeLayer(layer);
        if (window.map.getSource(src)) window.map.removeSource(src);
        window.map.addSource(src, { type: "image", url: dataUrl, coordinates });
        window.map.addLayer({ id: layer, type: "raster", source: src, paint: { "raster-opacity": 0.65, "raster-resampling": "nearest" } });
    };
    if (window.map.isStyleLoaded()) applyLayer(); else window.map.once("load", applyLayer);
}

function setFactorLayerVisible(factor, visible) {
    if (!window.map) return;
    const { layer } = factorLayerId(factor);
    if (window.map.getLayer(layer)) window.map.setLayoutProperty(layer, "visibility", visible ? "visible" : "none");
}

function removeFactorLayer(factor) {
    if (!window.map) return;
    const { src, layer } = factorLayerId(factor);
    if (window.map.getLayer(layer)) window.map.removeLayer(layer);
    if (window.map.getSource(src)) window.map.removeSource(src);
}

function factorLayerExists(factor) {
    if (!window.map) return false;
    return !!window.map.getLayer(factorLayerId(factor).layer);
}

// ==========================================================
// แสดงผลลัพธ์จาก GeoServer ผ่าน WMS (ตามแนวทาง Phase 2 ในคลิปเสียงอาจารย์)
// ใช้เมื่อ backend publish ขึ้น GeoServer สำเร็จ — ถ้าไม่สำเร็จจะใช้ภาพ PNG แทน
// ข้อดีของ WMS: สีมาจาก SLD ที่ตั้งบน GeoServer, ซูมแล้วคมขึ้น, และแชร์เลเยอร์
// ให้โปรแกรม GIS อื่น (QGIS/ArcMap) เปิดดูได้ด้วย URL เดียวกัน
// ==========================================================
function addSuitabilityWmsLayer(wmsUrl, layerName, bounds) {
    if (!window.map) return;
    const [west, south, east, north] = bounds;
    const tileUrl = `${wmsUrl}?service=WMS&version=1.1.1&request=GetMap`
        + `&layers=${encodeURIComponent(layerName)}`
        + `&bbox={bbox-epsg-3857}&width=256&height=256&srs=EPSG:3857`
        + `&format=image/png&transparent=true`;

    const applyLayer = () => {
        ["suitability-layer", "suitability-wms-layer"].forEach(id => {
            if (window.map.getLayer(id)) window.map.removeLayer(id);
        });
        ["suitability-src", "suitability-wms-src"].forEach(id => {
            if (window.map.getSource(id)) window.map.removeSource(id);
        });
        window.map.addSource("suitability-wms-src", {
            type: "raster", tiles: [tileUrl], tileSize: 256,
        });
        window.map.addLayer({
            id: "suitability-wms-layer", type: "raster", source: "suitability-wms-src",
            paint: { "raster-opacity": 0.8 },
        });
        window.map.fitBounds([[west, south], [east, north]], { padding: 30, duration: 800 });
    };
    if (window.map.isStyleLoaded()) applyLayer(); else window.map.once("load", applyLayer);
}

function addSuitabilityLayer(imageBase64, bounds) {
    if (!window.map) return;
    const [west, south, east, north] = bounds;
    const coordinates = [[west, north], [east, north], [east, south], [west, south]];
    const dataUrl = `data:image/png;base64,${imageBase64}`;

    const applyLayer = () => {
        ["suitability-layer", "suitability-wms-layer"].forEach(id => {
            if (window.map.getLayer(id)) window.map.removeLayer(id);
        });
        ["suitability-src", "suitability-wms-src"].forEach(id => {
            if (window.map.getSource(id)) window.map.removeSource(id);
        });
        window.map.addSource("suitability-src", { type: "image", url: dataUrl, coordinates: coordinates });
        window.map.addLayer({ id: "suitability-layer", type: "raster", source: "suitability-src", paint: { "raster-opacity": 0.8, "raster-resampling": "nearest" } });

        if (!window._suitabilityClickBound) {
            window._suitabilityClickBound = true;
            window.map.on("click", (e) => {
                if (!window.map.getLayer("suitability-layer")) return;
                const features = window.map.queryRenderedFeatures(e.point, { layers: ["suitability-layer"] });
                if (features.length === 0) return;
                if (typeof window.onSuitabilityMapClick === "function") {
                    window.onSuitabilityMapClick(e.lngLat.lng, e.lngLat.lat);
                }
            });
            window.map.on("mousemove", (e) => {
                if (!window.map.getLayer("suitability-layer")) { window.map.getCanvas().style.cursor = ""; return; }
                const features = window.map.queryRenderedFeatures(e.point, { layers: ["suitability-layer"] });
                window.map.getCanvas().style.cursor = features.length > 0 ? "pointer" : "";
            });
        }
        window.map.fitBounds([[west, south], [east, north]], { padding: 30, duration: 800 });
    };
    if (window.map.isStyleLoaded()) applyLayer(); else window.map.once("load", applyLayer);
}

function removeSuitabilityLayer() {
    if (!window.map) return;
    if (window.map.getLayer("suitability-layer")) window.map.removeLayer("suitability-layer");
    if (window.map.getSource("suitability-src")) window.map.removeSource("suitability-src");
}