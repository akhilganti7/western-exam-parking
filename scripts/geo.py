import json,math
from shapely.geometry import Polygon,LineString,Point
LAT0,LNG0=43.0065,-81.2765;KX=111320*math.cos(LAT0*math.pi/180);KY=110950
X=lambda o:(o-LNG0)*KX; Y=lambda a:-(a-LAT0)*KY
import os
HERE=os.path.dirname(os.path.abspath(__file__))
d=json.load(open(os.path.join(HERE,'..','data','osm_raw.json')))
def pairs(f): return [(f[i],f[i+1]) for i in range(0,len(f),2)]
blds=[];parks=[];others=[]
for id,t,co in d['POLY']:
    p=pairs(co)
    if len(p)<3: continue
    closed=p[0]==p[-1]
    if 'building' in t and closed: blds.append((id,t,Polygon(p)))
    elif t.get('amenity')=='parking' and closed: parks.append((id,t,Polygon(p)))
    else: others.append((id,t,p))
# relations: assemble outer rings
rw=d['relWays']
for rid,t,mem in d['RELS']:
    for ref,role in mem:
        if role!='outer' or str(ref) not in rw: continue
        p=pairs(rw[str(ref)])
        if len(p)>=4 and p[0]==p[-1]:
            g=Polygon(p)
            if 'building' in t: blds.append((rid,t,g))
            elif t.get('amenity')=='parking': parks.append((rid,t,g))
            else: others.append((rid,t,p))
        else: others.append((rid,t,p))
# multi-way outers: merge with polygonize
from shapely.ops import polygonize,unary_union
for rid,t,mem in d['RELS']:
    outs=[pairs(rw[str(r)]) for r,role in mem if role=='outer' and str(r) in rw]
    if not outs or all(len(p)>=4 and p[0]==p[-1] for p in outs): continue
    polys=list(polygonize(unary_union([LineString(p) for p in outs if len(p)>1])))
    for g in polys:
        if 'building' in t: blds.append((rid,t,g))
        elif t.get('amenity')=='parking': parks.append((rid,t,g))
nodes=d['hwNodes'];HW=d['HW']
