#!/usr/bin/env python3
"""
GeoSolar Sentinel — INTERMAGNET data fetcher v3
Obtiene el stopDate real de cada observatorio antes de pedir datos
"""
import urllib.request, urllib.error, json, sys
from datetime import datetime, timedelta, timezone

now = datetime.now(timezone.utc)
fmt = lambda d: d.strftime('%Y-%m-%dT%H:%M:%SZ')

OBSERVATORIES = {
    'HUA': {'name': 'Huancayo, Perú',       'lat': -12.0, 'lon': -75.3, 'region': 'Eje Andino'},
    'SJG': {'name': 'San Juan, Puerto Rico', 'lat':  18.1, 'lon': -66.2, 'region': 'Cuenca Caribe'},
    'KOU': {'name': 'Kourou, Guyana Fr.',    'lat':   5.2, 'lon': -52.7, 'region': 'Ecuador'},
}

HEADERS = {
    'User-Agent': 'GeoSolar-Sentinel/1.0 github.com/ingenierowilly/geosolar-proxy',
    'Accept': 'application/json',
}

def fetch_url(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def get_stop_date(code):
    """Obtener el stopDate real del observatorio via info endpoint"""
    url = f"https://imag-data.bgs.ac.uk/GIN_V1/hapi/info?id={code}/best-avail/PT1H/F"
    try:
        data = fetch_url(url)
        stop = data.get('stopDate','')
        print(f"  stopDate {code}: {stop}")
        return stop
    except Exception as e:
        print(f"  ❌ info {code}: {e}")
        return None

result = {
    'generated': fmt(now),
    'observatories': {}
}

for code, meta in OBSERVATORIES.items():
    print(f"\nProcesando {code}...")
    
    # Paso 1: obtener stopDate real
    stop_str = get_stop_date(code)
    if not stop_str:
        result['observatories'][code] = {**meta, 'ok': False, 'error': 'No info disponible'}
        continue
    
    stop_dt  = datetime.fromisoformat(stop_str.replace('Z','+00:00'))
    # Pedir las últimas 72 horas disponibles (hasta el stopDate real)
    start_dt = stop_dt - timedelta(hours=72)
    
    print(f"  Rango: {fmt(start_dt)} → {fmt(stop_dt)}")
    
    # Paso 2: pedir datos
    url = (
        f"https://imag-data.bgs.ac.uk/GIN_V1/hapi/data"
        f"?id={code}/best-avail/PT1H/F"
        f"&time.min={fmt(start_dt)}&time.max={fmt(stop_dt)}&format=json"
    )
    
    try:
        data = fetch_url(url, timeout=30)
        rows = data.get('data', [])
        print(f"  Rows: {len(rows)}")
        
        if not rows:
            raise ValueError('Sin datos')
        
        # Parsear
        pts = []
        for row in rows:
            try:
                F = float(row[1])
                if 0 < F < 99999:
                    pts.append({'t': row[0][:16]+'Z', 'F': round(F,1)})
            except: continue
        
        if not pts:
            raise ValueError('Sin valores F válidos')
        
        # Estadísticas
        vals   = sorted(p['F'] for p in pts)
        median = vals[len(vals)//2]
        max_dF = round(max(abs(p['F']-median) for p in pts[-24:] if pts), 1)
        status = 'PERTURBADO' if max_dF>50 else 'Activo' if max_dF>20 else 'Quieto'
        
        result['observatories'][code] = {
            **meta,
            'baseline_nT': round(median,1),
            'current_F':   round(pts[-1]['F'],1),
            'max_dF_24h':  max_dF,
            'status':      status,
            'pts':         pts[-48:],
            'data_through': fmt(stop_dt),
            'updated':     fmt(now),
            'ok': True
        }
        print(f"  ✅ F={pts[-1]['F']}nT baseline={median}nT ΔF={max_dF}nT {status}")
        
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8','replace')[:200]
        print(f"  ❌ HTTP {e.code}: {body}", file=sys.stderr)
        result['observatories'][code] = {**meta, 'ok': False, 'error': f'HTTP {e.code}'}
    except Exception as e:
        print(f"  ❌ {e}", file=sys.stderr)
        result['observatories'][code] = {**meta, 'ok': False, 'error': str(e)[:100]}

with open('intermagnet_data.json','w') as f:
    json.dump(result, f, separators=(',',':'))

ok = sum(1 for o in result['observatories'].values() if o.get('ok'))
print(f"\n{'✅' if ok>0 else '❌'} {ok}/{len(OBSERVATORIES)} OK → intermagnet_data.json")
