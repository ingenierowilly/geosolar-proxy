#!/usr/bin/env python3
"""
GeoSolar Sentinel — INTERMAGNET data fetcher
Corre via GitHub Actions cada hora
Guarda intermagnet_data.json en el repo para que la app lo lea sin CORS
"""
import urllib.request, json, sys
from datetime import datetime, timedelta, timezone

now   = datetime.now(timezone.utc)
start = now - timedelta(hours=25)
fmt   = lambda d: d.strftime('%Y-%m-%dT%H:%M:%SZ')

OBSERVATORIES = {
    'HUA': {'name': 'Huancayo, Perú',       'lat': -12.0, 'lon': -75.3, 'region': 'Eje Andino'},
    'SJG': {'name': 'San Juan, Puerto Rico', 'lat':  18.1, 'lon': -66.2, 'region': 'Cuenca Caribe'},
    'KOU': {'name': 'Kourou, Guyana Fr.',    'lat':   5.2, 'lon': -52.7, 'region': 'Ecuador'},
}

result = {
    'generated': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
    'observatories': {}
}

for code, meta in OBSERVATORIES.items():
    url = (
        f"https://imag-data.bgs.ac.uk/GIN_V1/hapi/data"
        f"?id={code}/best-avail/PT1M/xyzf"
        f"&time.min={fmt(start)}&time.max={fmt(now)}&format=json"
    )
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'GeoSolar-Sentinel/1.0 (github.com/ingenierowilly/geosolar-proxy)',
            'Accept': 'application/json'
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())

        rows = data.get('data', [])
        if not rows:
            raise ValueError('No data rows')

        # Parsear: row[0]=time, row[1]=[X,Y,Z], row[2]=F
        pts = []
        for row in rows:
            F = float(row[2]) if row[2] != '99999.0' else None
            if F and 0 < F < 99999:
                pts.append({'t': row[0], 'F': round(F, 1)})

        if not pts:
            raise ValueError('No valid F values')

        # Calcular línea base (mediana) y variación
        vals = sorted(p['F'] for p in pts)
        median = vals[len(vals)//2]

        # Guardar solo últimas 6h para reducir tamaño del JSON
        cutoff = (now - timedelta(hours=6)).strftime('%Y-%m-%dT%H:%M:%SZ')
        pts_6h = [p for p in pts if p['t'] >= cutoff]

        # Stats de la última hora
        cutoff1h = (now - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
        pts_1h   = [p for p in pts if p['t'] >= cutoff1h]
        dF_1h    = [abs(p['F'] - median) for p in pts_1h] if pts_1h else [0]
        max_dF   = round(max(dF_1h), 1)

        status = 'PERTURBADO' if max_dF > 50 else 'Activo' if max_dF > 20 else 'Quieto'

        result['observatories'][code] = {
            **meta,
            'baseline_nT': round(median, 1),
            'current_F':   round(pts[-1]['F'], 1) if pts else None,
            'max_dF_1h':   max_dF,
            'status':      status,
            'pts_6h':      pts_6h[-90:],  # max 90 puntos (1.5h a 1min cadencia)
            'updated':     now.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'ok':          True
        }
        print(f"✅ {code}: F={pts[-1]['F']}nT, ΔF(1h)=±{max_dF}nT, {status}")

    except Exception as e:
        print(f"❌ {code}: {e}", file=sys.stderr)
        result['observatories'][code] = {**meta, 'ok': False, 'error': str(e)}

with open('intermagnet_data.json', 'w') as f:
    json.dump(result, f, separators=(',', ':'))

print(f"✅ intermagnet_data.json generado — {len(json.dumps(result))} bytes")
