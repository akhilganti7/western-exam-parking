// Refresh data/osm_raw.json from OpenStreetMap.
// Paste this into the browser console on any page at https://api.openstreetmap.org
// (same origin, so no CORS issues). It downloads osm_raw.json when done.
// The OSM API caps one request at 50,000 nodes, so campus is fetched as a 4x3 grid.
(async () => {
  const LAT0 = 43.0065, LNG0 = -81.2765, KX = 111320 * Math.cos(LAT0 * Math.PI / 180), KY = 110950;
  const P = n => [Math.round((n.lon - LNG0) * KX * 10) / 10, Math.round(-(n.lat - LAT0) * KY * 10) / 10];
  const N = new Map(), W = new Map(), R = new Map();
  const x0 = -81.2930, x1 = -81.2540, y0 = 42.9955, y1 = 43.0185, nx = 4, ny = 3;
  for (let i = 0; i < nx; i++) for (let j = 0; j < ny; j++) {
    const a = x0 + (x1 - x0) * i / nx, b = x0 + (x1 - x0) * (i + 1) / nx, c = y0 + (y1 - y0) * j / ny, d = y0 + (y1 - y0) * (j + 1) / ny;
    const m = await (await fetch(`/api/0.6/map.json?bbox=${a.toFixed(5)},${c.toFixed(5)},${b.toFixed(5)},${d.toFixed(5)}`)).json();
    for (const e of m.elements) (e.type === 'node' ? N : e.type === 'way' ? W : R).set(e.id, e);
    console.log('tile', i, j, m.elements.length);
  }
  const keepT = ['name','highway','building','amenity','access','leisure','landuse','natural','waterway','water','footway','service','ref','short_name','addr:housenumber','addr:street','parking','fee','operator','layer','tunnel','bridge','area','surface','foot','official_name','alt_name'];
  const pick = t => { const o = {}; for (const k of keepT) if (t && t[k] != null) o[k] = t[k]; return o; };
  const hwIdx = new Map(), hwNodes = [], HW = [], POLY = [];
  for (const w of W.values()) {
    const t = w.tags || {}; if (!w.nodes) continue;
    if (t.highway) {
      const ids = w.nodes.map(id => { if (!N.has(id)) return -1; if (!hwIdx.has(id)) { hwIdx.set(id, hwNodes.length); hwNodes.push(P(N.get(id))); } return hwIdx.get(id); }).filter(i => i >= 0);
      HW.push([w.id, pick(t), ids]); if (t.area !== 'yes') continue;
    }
    if (t.building || t.amenity || t.leisure || t.landuse || t.natural || t.waterway || t.water)
      POLY.push([w.id, pick(t), w.nodes.filter(id => N.has(id)).map(id => P(N.get(id))).flat()]);
  }
  const RELS = []; for (const r of R.values()) { const t = r.tags || {}; if (!(t.building || t.amenity || t.leisure || t.landuse || t.natural || t.waterway || t.water)) continue; RELS.push([r.id, pick(t), r.members.filter(m => m.type === 'way').map(m => [m.ref, m.role])]); }
  const relWays = {}; for (const r of RELS) for (const [id] of r[2]) { const w = W.get(id); if (w && w.nodes) relWays[id] = w.nodes.filter(i => N.has(i)).map(i => P(N.get(i))).flat(); }
  const POI = []; for (const n of N.values()) { const t = n.tags; if (t && (t.name || t.entrance) && (t.amenity || t.entrance || t.building || t.shop || t.tourism || t.office)) POI.push([n.id, pick(t), P(n)]); }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify({ hwNodes, HW, POLY, RELS, relWays, POI })], { type: 'application/json' }));
  a.download = 'osm_raw.json'; a.click();
})();
