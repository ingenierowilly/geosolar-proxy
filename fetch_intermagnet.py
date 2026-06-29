#!/usr/bin/env python3
"""
GeoSolar Sentinel — INTERMAGNET data fetcher v4
Usa fechas históricas conocidas — BGS bloquea info requests desde GitHub IPs
Estrategia: probar rangos de fechas hacia atrás hasta encontrar datos
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

def try_fetch_data(code, end_dt, hours=48):
    """Intenta obtener datos para un rango específico"""
    start_dt = end_dt - timedelta(hours=hours)
    url = (
        f"https://imag-data.bgs.ac.uk/GIN_V1/hapi/data"
        f"?id={code}/best-avail/PT1H/F"
        f"&time.min={fmt(start_dt)}&time.max={fmt(end_dt)}&format=json"
    )
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read()), start_dt, end_dt

result = {
    'generated': fmt(now),
    'observatories': {}
}

for code, meta in OBSERVATORIES.items():
    print(f"\nProcesando {code}...")
    success = False

    # Probar ventanas de tiempo hacia atrás desde hace 1 día hasta hace 10 días
    # INTERMAGNET tiene retraso variable de 1-7 días según el observatorio
    for days_back in range(1, 11):
        end_dt   = now - timedelta(days=days_back)
        # Redondear a hora exacta para evitar problemas de formato
        end_dt   = end_dt.replace(minute=0, second=0, microsecond=0)

        try:
            data, start_dt, end_dt = try_fetch_data(code, end_dt, hours=48)
            rows = data.get('data', [])

            # Filtrar filas válidas
            pts = []
            for row in rows:
                try:
                    F = float(row[1])
                    if 0 < F < 99999:
                        pts.append({'t': row[0][:16]+'Z', 'F': round(F,1)})
                except: continue

            if not pts:
                print(f"  día -{days_back}: HTTP OK pero sin datos F válidos")
                continue

            # Éxito — calcular estadísticas
            vals   = sorted(p['F'] for p in pts)
            median = vals[len(vals)//2]
            window = pts[-24:] if len(pts) >= 24 else pts
            max_dF = round(max(abs(p['F']-median) for p in window), 1)
            status = 'PERTURBADO' if max_dF>50 else 'Activo' if max_dF>20 else 'Quieto'

            result['observatories'][code] = {
                **meta,
                'baseline_nT': round(median, 1),
                'current_F':   round(pts[-1]['F'], 1),
                'max_dF_24h':  max_dF,
                'status':      status,
                'pts':         pts[-48:],
                'data_through': fmt(end_dt),
                'delay_days':   days_back,
                'updated':      fmt(now),
                'ok':           True
            }
            print(f"  ✅ día -{days_back}: F={pts[-1]['F']}nT "
                  f"baseline={median}nT ΔF={max_dF}nT {status} "
                  f"({len(pts)} puntos)")
            success = True
            break

        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8','replace')[:100]
            print(f"  día -{days_back}: HTTP {e.code} — {body[:60]}")
            continue
        except Exception as e:
            print(f"  día -{days_back}: {str(e)[:80]}")
            continue

    if not success:
        print(f"  ❌ {code}: sin datos en los últimos 10 días")
        result['observatories'][code] = {
            **meta, 'ok': False,
            'error': 'Sin datos disponibles (retraso >10 días o observatorio inactivo)'
        }

with open('intermagnet_data.json', 'w') as f:
    json.dump(result, f, separators=(',', ':'))

ok = sum(1 for o in result['observatories'].values() if o.get('ok'))
print(f"\n{'✅' if ok > 0 else '❌'} {ok}/{len(OBSERVATORIES)} observatorios con datos")
