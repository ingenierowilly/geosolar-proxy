#!/usr/bin/env python3
"""
GeoSolar Sentinel — INTERMAGNET data fetcher v2
Corre via GitHub Actions cada hora.
INTERMAGNET best-avail tiene retraso de ~1-3 días — pedimos datos de hace 5 días a ayer.
"""
import urllib.request, urllib.error, json, sys
from datetime import datetime, timedelta, timezone

now   = datetime.now(timezone.utc)
# Ventana: hace 5 días → hace 12 horas (cubre el retraso típico de INTERMAGNET)
end   = now - timedelta(hours=12)
start = now - timedelta(days=5)
fmt   = lambda d: d.strftime('%Y-%m-%dT%H:%M:%SZ')

OBSERVATORIES = {
    'HUA': {'name': 'Huancayo, Perú',       'lat': -12.0, 'lon': -75.3, 'region': 'Eje Andino'},
    'SJG': {'name': 'San Juan, Puerto Rico', 'lat':  18.1, 'lon': -66.2, 'region': 'Cuenca Caribe'},
    'KOU': {'name': 'Kourou, Guyana Fr.',    'lat':   5.2, 'lon': -52.7, 'region': 'Ecuador'},
}

result = {
    'generated': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
    'data_range': f"{fmt(start)} / {fmt(end)}",
    'observatories': {}
}

for code, meta in OBSERVATORIES.items():
    # Usar cadencia horaria PT1H y solo campo F (magnitud total)
    # Más liviano y con menos probabilidad de error 400
    url = (
        f"https://imag-data.bgs.ac.uk/GIN_V1/hapi/data"
        f"?id={code}/best-avail/PT1H/F"
        f"&time.min={fmt(start)}&time.max={fmt(end)}&format=json"
    )
    print(f"Fetching {code}...")
    print(f"  URL: {url}")

    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'GeoSolar-Sentinel/1.0 github.com/ingenierowilly/geosolar-proxy',
            'Accept':     'application/json',
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            raw  = r.read()
            data = json.loads(raw)

        rows = data.get('data', [])
        print(f"  Rows recibidos: {len(rows)}")
        if not rows:
            raise ValueError('Sin datos en el rango solicitado')

        # Parsear: row[0]=timestamp, row[1]=F
        pts = []
        for row in rows:
            try:
                F = float(row[1])
                if 0 < F < 99999:
                    pts.append({'t': row[0][:16]+'Z', 'F': round(F, 1)})
            except (ValueError, IndexError):
                continue

        if not pts:
            raise ValueError('Sin valores F válidos')

        # Línea base: mediana
        vals   = sorted(p['F'] for p in pts)
        median = vals[len(vals)//2]

        # ΔF máximo en las últimas 24h disponibles
        last_24h  = pts[-24:] if len(pts) >= 24 else pts
        max_dF    = round(max(abs(p['F'] - median) for p in last_24h), 1)
        status    = 'PERTURBADO' if max_dF > 50 else 'Activo' if max_dF > 20 else 'Quieto'

        # Últimos 48 puntos (2 días horarios) para el sparkline
        pts_recent = pts[-48:]

        result['observatories'][code] = {
            **meta,
            'baseline_nT': round(median, 1),
            'current_F':   round(pts[-1]['F'], 1),
            'max_dF_24h':  max_dF,
            'status':      status,
            'pts':         pts_recent,
            'data_points': len(pts),
            'updated':     now.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'ok':          True
        }
        print(f"  ✅ {code}: F={pts[-1]['F']}nT baseline={median}nT ΔF={max_dF}nT {status}")

    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')[:200]
        print(f"  ❌ {code} HTTP {e.code}: {body}", file=sys.stderr)
        result['observatories'][code] = {**meta, 'ok': False, 'error': f"HTTP {e.code}"}
    except Exception as e:
        print(f"  ❌ {code}: {e}", file=sys.stderr)
        result['observatories'][code] = {**meta, 'ok': False, 'error': str(e)[:100]}

with open('intermagnet_data.json', 'w') as f:
    json.dump(result, f, separators=(',', ':'))

ok_count = sum(1 for o in result['observatories'].values() if o.get('ok'))
print(f"\n{'✅' if ok_count > 0 else '❌'} {ok_count}/{len(OBSERVATORIES)} observatorios OK")
print(f"   Archivo: intermagnet_data.json")
