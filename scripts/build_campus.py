"""Turn the raw OpenStreetMap pull (data/osm_raw.json) into campus.json for the app.

Run:  pip install shapely   then   python scripts/build_campus.py
Output: campus.json in the repo root (coords are metres from LAT0/LNG0, x east, y south).

What it does:
  1. builds the walking network from OSM highways (footways, paths, stairs, roads)
  2. matches every exam building code to its OSM outline (table BL below)
  3. matches every visitor lot / street spot to its OSM outline (table LOTS below)
  4. finds a few "door" nodes on the network for each building and lot
  5. simplifies buildings, lots, green space and water for drawing

To refresh the raw map data, see scripts/fetch_osm.js.
Edit LOTS when Western changes zones, hours or rates."""
import json, math, heapq, os
from shapely.geometry import Polygon, Point, LineString
from shapely.ops import nearest_points
from geo import *   # loads data/osm_raw.json, sets X/Y projection, HERE

R1 = lambda v: int(round(v))
def flat(coords): return [R1(c) for xy in coords for c in xy]
def simp(poly, tol=0.8):
    g = poly.simplify(tol, preserve_topology=True)
    return list(g.exterior.coords)[:-1]

# ---------- walking graph ----------
NOWALK = {'platform', 'bus_stop', 'construction', 'proposed', 'motorway', 'motorway_link', 'elevator', 'corridor'}
PATHS = {'footway', 'path', 'pedestrian', 'cycleway', 'steps', 'track', 'living_street', 'bridleway'}
MAJOR = {'primary', 'primary_link', 'secondary', 'secondary_link', 'tertiary', 'tertiary_link'}
def cls(t):
    h = t.get('highway')
    if h in PATHS: return 'p'
    if h in MAJOR: return 'M'
    return 'm'
roads = []          # [class, name, [node idx...]]
walk = []           # ways usable on foot
for wid, t, ids in HW:
    h = t.get('highway')
    if h in NOWALK or len(ids) < 2: continue
    if t.get('area') == 'yes' and h == 'pedestrian': pass
    c = cls(t)
    nowalk = t.get('foot') == 'no' or (t.get('access') in ('no', 'private') and t.get('foot') not in ('yes', 'designated')) or (t.get('tunnel') == 'yes' and h != 'footway')
    # kind: 0 path/normal, 1 steps, 2 service, 3 big road ; -1 not walkable
    kind = -1 if nowalk else 1 if h == 'steps' else 3 if c == 'M' else 2 if h == 'service' else 0
    roads.append([c, t.get('name', '') if c != 'p' else '', ids, kind])
    if nowalk: continue
    walk.append((ids, h))

# keep only nodes used by roads, re-index
used = sorted({i for r in roads for i in r[2]})
remap = {o: n for n, o in enumerate(used)}
N2 = [nodes[o] for o in used]
for r in roads: r[2] = [remap[i] for i in r[2]]
walk = [([remap[i] for i in ids], h) for ids, h in walk]

# adjacency for checks
adj = {}
def addE(a, b, w):
    adj.setdefault(a, []).append((b, w)); adj.setdefault(b, []).append((a, w))
pen = {'steps': 1.15, 'primary': 1.3, 'secondary': 1.25, 'tertiary': 1.15, 'service': 1.05}
for ids, h in walk:
    f = pen.get(h, 1.0)
    for a, b in zip(ids, ids[1:]):
        dist = math.dist(N2[a], N2[b]); addE(a, b, dist * f)

# largest connected component only for snapping
seen = set(); comps = []
for s in adj:
    if s in seen: continue
    st = [s]; comp = set([s]); seen.add(s)
    while st:
        u = st.pop()
        for v, _ in adj[u]:
            if v not in seen: seen.add(v); comp.add(v); st.append(v)
    comps.append(comp)
main = max(comps, key=len)
print('walk nodes', len(adj), 'main comp', len(main), 'comps', len(comps))
mainlist = sorted(main)

def cands(geom, extra=15, cap=10):
    """walkable nodes near a shape: [[node, gap metres], ...] (best first)"""
    out = []
    for i in mainlist:
        x, y = N2[i]
        if abs(x - geom.centroid.x) > 500 or abs(y - geom.centroid.y) > 500: continue
        dd = geom.exterior.distance(Point(x, y)) if hasattr(geom, 'exterior') else geom.distance(Point(x, y))
        if hasattr(geom, 'exterior') and geom.contains(Point(x, y)): dd = 0
        out.append((dd, i))
    out.sort(); lim = out[0][0] + extra
    return [[i, round(dd)] for dd, i in out if dd <= lim][:cap]

def snap(geom):
    """nearest walkable node (main component) to a shapely geometry"""
    best = None
    for i in mainlist:
        x, y = N2[i]
        if abs(x - geom.centroid.x) > 400 or abs(y - geom.centroid.y) > 400: continue
        d = geom.exterior.distance(Point(x, y)) if hasattr(geom, 'exterior') else geom.distance(Point(x, y))
        if best is None or d < best[0]: best = (d, i)
    return best

# ---------- buildings (every on-map code from uwo.ca/westerndir/buildings/abbr) ----------
# code, official name, OSM building name (or None), (lat,lng) fallback point
BL = [
 ('3M','3M Centre','3M Centre',None),('ACEB','Amit Chakma Engineering Building','Amit Chakma Engineering Building',None),
 ('AFAR','Advanced Facility for Avian Research','Advanced Facility for Avian Research',None),('AH','Alumni Hall','Alumni Hall',None),
 ('AHB','Arts & Humanities Building','Arts & Humanities',None),('AHR','Alumni House Residence','Alumni House (Residence)',None),
 ('AP','Academic Pavilion (Brescia)','Brescia University College',None),('AUHR','Ausable Hall Residence','Ausable Hall (Residence)',None),
 ('BAHR','Bayfield Hall Residence','Bayfield Hall (Residence)',None),('BGG','Biological & Geological Greenhouses','Greenhouses',None),
 ('BGSB','Biological & Geological Sciences Building','Biological & Geological Sciences',None),('BHR','Beaver Hall Residence','Beaver Hall (Residence)',None),
 ('BIL','Beryl Ivey Library (Brescia)','Brescia University College',None),('BIO','Biotron','Biotron Experimental Climate Change Research Centre',None),
 ('BLWT','Boundary Layer Wind Tunnel','Boundary Layer Wind Tunnel Laboratory',None),('BP','Books Plus',None,(43.0013894,-81.2766204)),
 ('BUC','Brescia University College','Brescia University College',None),('CB','Collip Building','Collip Medical Research Building',None),
 ('CC','Convergence Centre','Convergence Centre',None),('CHB','Chemistry Building','Chemistry Building',None),
 ('CHR','Clare Hall Residence & Mercato',None,(43.0026098,-81.2849024)),('CMLP','Claudette MacKay-Lassonde Pavilion','Claudette Mackay-Lassonde Pavilion',None),
 ('CO','Cronyn Observatory','Cronyn Observatory',None),('CSB','Dr. Don Rix Clinical Skills Learning Building','Dr. Don Rix Clinical Skills Learning Building',None),
 ('CYDC','Child & Youth Development Clinic','Child & Youth Development Clinic',None),('DHR','Delaware Hall Residence','Delaware Hall (Residence)',None),
 ('DSB','Dental Sciences Building','Dental Sciences Building',None),('EC','Elborn College','Elborn College',None),
 ('EHR','Essex Hall Residence','Essex Hall',None),('ELHR','Elgin Hall Residence','Elgin Hall (Residence)',None),
 ('FEB','Althouse Faculty of Education Building','Althouse',None),('FNB','FIMS & Nursing Building','FIMS & Nursing Building',None),
 ('GSB','Graphic Services Building','Graphic Services',None),('HSA','Health Sciences Addition','Health Sciences Addition',None),
 ('HSB','Labatt Health Sciences Building','Health Sciences Building',None),('HUC','Huron University College','Huron University College',None),
 ('IGAB','International & Graduate Affairs Building','International & Graduate Affairs',None),
 ('IMTI','Integrated Manufacturing Technologies Institute (NRC)','National Research Council of Canada',None),
 ('ISLC','Ivey Spencer Leadership Centre','Spencer Hotel & Conference Centre',None),('IVEY','Richard Ivey Building','Richard Ivey Building',None),
 ('KB','Kresge Building','Kresge Building',None),('KUC',"King's University College",'Monsignor Wemple Hall',None),
 ('LAHR','Lambton Hall Residence','Lambton Hall (Residence)',None),('LB','Josephine Spencer Niblett Law Building','Law School',None),
 ('LHSC-UH','University Hospital (LHSC)',None,(43.0123,-81.2750)),('LOHR','London Hall Residence','London Hall',None),
 ('LRI','Lawson Research Institute (St. Joseph\'s)',None,(43.0005946,-81.2545574)),('LWH','Lawson Hall','Lawson Hall',None),
 ('MB','Music Building','Music Building',None),('MC','Middlesex College','Middlesex College',None),('MG','McIntosh Gallery','McIntosh Art Gallery',None),
 ('MHR','Medway Hall Residence','Medway Hall (Residence)',None),('MOG','Gordon J. Mogenson Building','Mogenson Centre',None),
 ('MSA','Material Science Addition','Material Sciences Addition',None),('MSB','Medical Sciences Building','Medical Sciences Building',None),
 ('NCB','North Campus Building','North Campus Building',None),('NSC','Natural Sciences Centre','Natural Sciences Building',None),
 ('OHR','Ontario Hall Residence','Ontario Hall',None),('PAB','Physics & Astronomy Building','Physics Building',None),
 ('PHFM','Western Centre for Public Health & Family Medicine','Western Centre for Public Health and Family Medicine',None),
 ('PHR','Perth Hall Residence','Perth Hall',None),('PP','Power Plant','Power Plant',None),
 ('RRI','Robarts Research Institute','Robarts Research Institute',None),('SC','The Stiller Centre','The Stiller Centre',None),
 ('SDRI','Siebens Drake Research Institute','Siebens Centre',None),('SEB','Spencer Engineering Building','Spencer Engineering Building',None),
 ('SEI','Schmeichel Entrepreneurship & Innovation Building','Ronald D. Schmeichel Building for Entrepreneurship and Innovation',None),
 ('SH','Somerville House','Somerville House',None),('SJB','St. James Building (Brescia)','Brescia University College',None),
 ('SJHC',"St. Joseph's Health Care",None,(43.0005946,-81.2545574)),('SMHR','Saugeen-Maitland Hall Residence','Saugeen Maitland Hall (Residence)',None),
 ('SSB','Support Services Building','Support Services Building',None),('SSC','Social Science Centre','Social Science Center',None),
 ('STAB','Staging Building','Staging Building',None),('STVH','Stevenson Hall','Stevenson Hall',None),
 ('SYHR','Sydenham Hall Residence','Sydenham Hall (Residence)',None),('TC','Talbot College','Talbot College',None),
 ('TDS','Western Alumni Stadium (TD Stadium)','@stadium',None),('TEB','Thompson Engineering Building','Thompson Engineering Building',None),
 ('TH','Thames Hall','Thames Hall',None),('TL','Taylor Library','Taylor Library',None),
 ('TRAC','Thompson Recreation & Athletic Centre','Thompson Arena',None),('UC','University College','University College',None),
 ('UCC','University Community Centre','University Community Center',None),('UH','Ursuline Hall (Brescia)','Brescia University College',None),
 ('UYCC','University YMCA Child Care',None,(43.0011862,-81.2766008)),('VAC','John Labatt Visual Arts Centre','John Labatt Visual Art Centre',None),
 ('WH','Westminster Hall','Westminister Hall',None),('WIRB','Western Interdisciplinary Research Building','Western Interdisciplinary Research Building',None),
 ('WL','Weldon Library','Weldon Library',None),('WLL','Wampum Learning Lodge (at Althouse)','Althouse',None),
 ('WMCC','Windermere Manor Conference Centre','Windermere Manor Hotel & Conference Centre',None),
 ('WMH','Windermere Manor Hotel','Windermere Manor Hotel & Conference Centre',None),('WSC','Western Science Centre','Western Science Centre',None),
 ('WSRC','Western Student Recreation Centre','Western Student Recreation Centre',None),('WSSB','Western Student Services Building','Western Student Services Building',None),
 ('WTC','Western Tennis Club (University Tennis Centre)',None,(43.0064807,-81.2696877)),('WVB','West Valley Building','West Valley Building',None),
]
BL = [b for b in BL if not b[0].endswith('HR')]   # residences are never exam rooms
byname = {}
for bid, t, g in blds:
    n = t.get('name')
    if n and (n not in byname or g.area > byname[n][1].area): byname[n] = (bid, g)
stadium = [Polygon(p) for i, t, p in others if t.get('leisure') == 'stadium']
EXB = []; SHAPES = []; done = {}
for code, full, osm, ll in BL:
    if osm == '@stadium': g, bid = stadium[0], 'stadium'
    elif osm: bid, g = byname[osm]
    else:
        pt = Point(X(ll[1]), Y(ll[0]))
        near = sorted(((g.distance(pt), bid, g) for bid, t, g in blds if g.area > 150 and g.distance(pt) < 40), key=lambda z: z[0])
        if near: _, bid, g = near[0]
        else: bid, g = None, pt.buffer(14)
        print('placed', code, 'on', 'building' if near else 'point', round(near[0][0]) if near else '')
    dd, node = snap(g)
    p = nearest_points(g.exterior, Point(*N2[node]))[0]
    if bid not in done:
        done[bid] = code; SHAPES.append([code, flat(simp(g, .8))])
    EXB.append(dict(c=code, n=full, x=R1(g.centroid.x), y=R1(g.centroid.y), id=bid, shape=done[bid], gap=round(dd), cand=cands(g, 12, 12), approx=1 if (osm is None or code in ('AP','BIL','SJB','UH','WLL')) else 0))
    if dd > 60: print('far snap', code, round(dd))
print('buildings', len(EXB))

# ---------- parking ----------
pk = {k: (id, t, g) for k, (id, t, g) in enumerate(parks)}
def P(k): return pk[k][2]
LOTS = [
 dict(n='Huron Flats', h='1971', win='all', max=12, k=25, d='Huge lot north of Alumni Stadium. Cheapest full day.'),
 dict(n='Althouse / Ontario Hall Student Lot', h='2009', win='all', max=12, k=10, d='Big lot west of Althouse, off Western Rd. Cheap full day.'),
 dict(n='Ontario Hall Pay & Display', h='1990', win='all', max=None, k=44, d='Between Ontario Hall and Althouse.'),
 dict(n='Althouse College Pay & Display', h='1988', win='all', max=None, k=22, d='East side of Althouse, by Western Rd.'),
 dict(n='Springett Student Lot', h='2420', win='all', max=12, k=54, pt=(-300, 30), d='End of the Springett turn-in off Western Rd, south of Huron.'),
 dict(n='Springett Employee Lot', h='3824', win='after4', max=12, k=54, pt=(-190, -5), d='Visitors 4 pm to 7 am only.'),
 dict(n='Springett Pay & Display', h='2007', win='all', max=None, k=54, pt=(-115, -30), d='East end of the Springett lots, closest to Western Rd.'),
 dict(n='Huron College Pay & Display', h='2004', win='all', max=None, k=46, d='Gated area north of the Springett lots. Leave by 7 am if overnight.'),
 dict(n='Essex / London Hall Pay & Display', h='1987', win='all', max=12, k=33, d='$3/hr, $12 max per session.'),
 dict(n='Perth Hall', h='1989', win='all', max=None, k=41, d='Small lot north of Perth Hall.'),
 dict(n='Elborn College Lot', h='1992', win='after4', max=None, k=27, ev=1, d='Visitors 4 pm to 7 am only.'),
 dict(n='West Campus Lot', h='8398', win='all', max=None, k=56, ev=1, d='Down Brescia Rd, big lot on the left.'),
 dict(n='South Valley Lot', h='8386', win='after4', max=None, k=49, d='Big lot north of the Rec Centre, off Huron Dr.'),
 dict(n='Alumni Thompson Lot', h='3865', win='acc', max=None, pt=(150, 125), ev=1, d='Accessible parking only right now (construction). Southwest of Alumni Hall.'),
 dict(n='Power Plant / Health Sciences', h='1994', win='all', max=None, k=58, d='Small lot between Health Sciences and the heating plant.'),
 dict(n='Weldon Pay & Display', h='2001', win='all', max=None, k=45, ev=1, d='Between Weldon Library and Law.'),
 dict(n='Talbot Pay & Display', h='1985', win='all', max=None, k=86, pt=(585, -100), d='Across the street from Talbot College.'),
 dict(n='Music Building Lot', h='1986', win='all', max=None, pt=(455, 5), d='South side, right beside the Music Building.'),
 dict(n='Social Science Lot (visitor side)', h=None, win='all', max=21, rule='ssc', k=48, d='West side as you enter. 2 hrs at $1.50/half hr, then the $21 day rate.'),
 dict(n='Siebens / Medical Sciences Lot', h=None, win='after5', max=8, k=47, d='Patients only 7 am to 5 pm. Visitors after 5 pm, $8 max.'),
 dict(n='Physics & Astronomy Lot', h='1978', win='all', max=None, k=83, d='Northeast of Physics & Astronomy.'),
 dict(n='Middlesex Lot', h='1977', win='after4', max=None, k=84, d='Off Perth Dr, north of Middlesex College. Visitors 4 pm to 7 am.'),
 dict(n='B&G Lot', h='1981', win='all', max=None, k=85, d='Beside the Middlesex lot, off Perth Dr.'),
 dict(n='North Campus Building Pay & Display', h='1982', win='all', max=None, k=98, d='Between Visual Arts and North Campus Building.'),
 dict(n='Visual Arts Lot', h='1976', win='after4', max=None, k=159, ev=1, d='Between Visual Arts and WIRB. Visitors 4 pm to 7 am only.'),
 dict(n='Dental Circle', h='1980', win='all', max=None, pt=(232, -548), d='On Dental Circle, east of Dental Sciences.'),
 dict(n='Taylor Library Loading Dock', h='2008', win='all', max=None, pt=(268, -625), d='South of Chemistry, off Dental Circle. A few spots only.'),
 dict(n='Delaware Hall', h='1983', win='all', max=None, pt=(600, -290), d='North, lower area by Delaware Hall.'),
 dict(n='University Drive street spots', h='1975', win='all', max=None, pt=(700, -135), d='Signed paid spots along University Dr.'),
 dict(n='Medway Lot', h='1984', win='all', max=None, k=87, d='Behind Elgin Hall, off University Dr.'),
 dict(n='Support Services Upper Pay & Display', h='2002', win='all', max=None, rule='ssb', k=61, ev=1, d='Off Western Rd. No parking 8 pm to 7 am.'),
 dict(n='Support Services Lower Lot', h='1997', win='all', max=None, k=50, d='Below the Support Services Building.'),
 dict(n='Avian Research Lot', h='1999', win='all', max=None, pt=(-300, -455), d='Beside the Avian Research building.'),
 dict(n='Saugeen-Maitland Hall', h='1996', win='all', max=None, k=68, d='West side of Saugeen-Maitland.'),
 dict(n='Lambton Hall', h='1995', win='all', max=None, k=64, d='Between the Lambton permit area and Lambton Hall.'),
 dict(n='Bayfield Hall Lot', h='1998', win='all', max=None, k=65, ev=1, d='Next to Bayfield Hall, north campus.'),
 dict(n='Westminster Pay & Display', h='1979', win='all', max=None, k=105, ev=1, d='Off Windermere Rd, far north edge.'),
 dict(n='Waterloo St (free street parking)', h=None, win='street', street=2, pt=(1700, -535), d="Free, just south of Epworth Ave by King's. 2-hour limit."),
]
for l in LOTS:
    g = P(l['k']) if 'k' in l else None
    if 'pt' in l: c = Point(*l['pt'])
    else: c = g.representative_point() if g.centroid.within(g) is False else g.centroid
    l['x'], l['y'] = R1(c.x), R1(c.y)
    dd, node = snap(Point(c.x, c.y).buffer(1) if g is None or 'pt' in l else g)
    l['node'] = node; l['gap'] = round(dd)
    l['cand'] = cands(g if (g is not None and 'pt' not in l) else Point(c.x, c.y).buffer(4), 15, 10)
    if g is not None: l['poly'] = flat(simp(g, 1))
    l.pop('k', None); l.pop('pt', None)
    if dd > 60: print('far lot snap', l['n'], round(dd))

# ---------- base layers ----------
def keep(g): return -1700 < g.centroid.x < 2500 and -1400 < g.centroid.y < 1200
campus_ids = {e['id'] for e in EXB}
uni = [Polygon(p) for i, t, p in others if t.get('amenity') == 'university' and len(p) > 3 and p[0] == p[-1]]
bl = []
for bid, t, g in blds:
    if g.area < 12 or not keep(g): continue
    kind = 2 if bid in campus_ids else 1 if (t.get('name') or any(u.contains(g.centroid) for u in uni) or g.area > 1500) else 0
    bl.append([kind, flat(simp(g, .9 if kind else 1.3))])
pl = [flat(simp(g, 1)) for id, t, g in parks if keep(g) and g.area > 60]
green, water, wline, pitch = [], [], [], []
for i, t, p in others:
    if len(p) < 2: continue
    closed = len(p) > 3 and p[0] == p[-1]
    if t.get('waterway') and not closed: wline.append(flat(LineString(p).simplify(1.5).coords)); continue
    if not closed: continue
    g = Polygon(p)
    if not g.is_valid: g = g.buffer(0)
    if g.geom_type != 'Polygon' or not keep(g): continue
    if t.get('natural') == 'water' or t.get('water'): water.append(flat(simp(g, 1.5)))
    elif t.get('leisure') in ('pitch', 'track', 'stadium'): pitch.append(flat(simp(g, 1)))
    elif t.get('landuse') in ('grass', 'recreation_ground') or t.get('leisure') in ('park', 'garden', 'playground') or t.get('natural') in ('wood', 'scrub') or t.get('landuse') == 'forest':
        green.append([1 if (t.get('natural') == 'wood' or t.get('landuse') == 'forest') else 0, flat(simp(g, 1.5))])
# relations with water/wood outers
for rid, t, mem in d['RELS']:
    for ref, role in mem:
        if role != 'outer' or str(ref) not in rw: continue
        p = pairs(rw[str(ref)])
        if len(p) < 4 or p[0] != p[-1]: continue
        g = Polygon(p).buffer(0)
        if g.geom_type != 'Polygon': continue
        if t.get('natural') == 'water': water.append(flat(simp(g, 1.5)))
        elif t.get('natural') == 'wood': green.append([1, flat(simp(g, 1.5))])
unif = [flat(simp(u, 2)) for u in uni if u.area > 200000]

out = dict(v=1, lat0=LAT0, lng0=LNG0, nodes=[R1(c) for xy in N2 for c in xy],
           roads=roads, bld=bl, park=pl, green=green, water=water, wline=wline, pitch=pitch, uni=unif,
           exam=EXB, examShapes=SHAPES, lots=LOTS)
s = json.dumps(out, separators=(',', ':'))
open(os.path.join(HERE, '..', 'campus.json'), 'w').write(s)
print('size KB', len(s) // 1024, {k: len(v) for k, v in out.items() if isinstance(v, list)})
for k in ['nodes', 'roads', 'bld', 'park', 'green', 'water', 'exam', 'lots']:
    print(k, len(json.dumps(out[k], separators=(',', ':'))) // 1024, 'KB')
