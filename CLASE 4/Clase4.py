# -*- coding: utf-8 -*-
"""
Descarga ERA5 (2m_temperature) horario para 2024-12-25,
recorta al Partido de Azul (Provincia de Buenos Aires, AR),
promedia espacialmente por hora y grafica Temp (°C) vs Hora (America/Argentina/Buenos_Aires).
"""

import os
from datetime import datetime
import json

import cdsapi
import xarray as xr
import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import mapping
from unidecode import unidecode
import matplotlib.pyplot as plt

# -----------------------------
# CONFIG
# -----------------------------
# Ruta al GeoJSON de departamentos (IGN)
RUTA_GEOJSON = "departamentos_IGN.geojson"  # cambia si tu archivo se llama distinto

PROV_BSAS = "BUENOS AIRES"
DEPTO_AZUL = "AZUL"

ANIO  = "2024"
MES   = "12"
DIA   = "25"

SALIDA_NC   = f"era5_azul_{ANIO}-{MES}-{DIA}.nc"
SALIDA_CSV  = f"era5_azul_{ANIO}-{MES}-{DIA}_horario.csv"
SALIDA_FIG  = f"era5_azul_{ANIO}-{MES}-{DIA}_hora_vs_temp.png"

TZ_LOCAL = "America/Argentina/Buenos_Aires"

# -----------------------------
# 1) Cargar póligono del Partido de Azul
# -----------------------------
def _norm(s):
    if s is None:
        return ""
    return unidecode(str(s)).upper().strip()

gdf = gpd.read_file(RUTA_GEOJSON)

# Intentamos detectar nombres de columnas comunes
cols = {c.lower(): c for c in gdf.columns}
cand_depto = [k for k in cols if k in ("departamento", "depto", "nombre", "nam", "name", "dpto", "departamen")]
cand_prov  = [k for k in cols if k in ("provincia", "prov", "prov_name", "provincia_nombre", "province")]

if not cand_depto:
    raise RuntimeError("No pude identificar la columna de 'departamento' en el GeoJSON. Renombrá o ajustá el script.")
if not cand_prov:
    raise RuntimeError("No pude identificar la columna de 'provincia' en el GeoJSON. Renombrá o ajustá el script.")

col_depto = cols[cand_depto[0]]
col_prov  = cols[cand_prov[0]]

gdf["_DEPTO_NORM"] = gdf[col_depto].apply(_norm)
gdf["_PROV_NORM"]  = gdf[col_prov].apply(_norm)

sel = gdf[(gdf["_DEPTO_NORM"] == _norm(DEPTO_AZUL)) & (gdf["_PROV_NORM"] == _norm(PROV_BSAS))]
if sel.empty:
    # fallback: buscar por departamento solamente
    sel = gdf[gdf["_DEPTO_NORM"] == _norm(DEPTO_AZUL)]

if sel.empty:
    raise RuntimeError("No encontré el polígono de 'AZUL' en el GeoJSON.")

# Unificar geometría por si hay múltiples features
sel = sel.to_crs("EPSG:4326")
poly = sel.unary_union

# Bounding box (N, W, S, E) para reducir tamaño de descarga
minx, miny, maxx, maxy = poly.bounds  # (W, S, E, N)
N, W, S, E = maxy, minx, miny, maxx

# -----------------------------
# 2) Descargar ERA5 (2m_temperature) horario del día
# -----------------------------
if not os.path.exists(SALIDA_NC):
    c = cdsapi.Client()  # requiere ~/.cdsapirc con tus credenciales

    # Todas las 24 horas del día
    horas = [f"{h:02d}:00" for h in range(24)]

    req = {
        "product_type": "reanalysis",
        "variable": ["2m_temperature"],
        "year": [ANIO],
        "month": [MES],
        "day": [DIA],
        "time": horas,
        "format": "netcdf",
        # area = North, West, South, East
        "area": [float(f"{N:.4f}"), float(f"{W:.4f}"), float(f"{S:.4f}"), float(f"{E:.4f}")]
    }

    c.retrieve("reanalysis-era5-single-levels", req, SALIDA_NC)
else:
    print(f"[INFO] Ya existe {SALIDA_NC}, no se descarga de nuevo.")

# -----------------------------
# 3) Abrir NetCDF, recortar por polígono y promediar espacialmente
# -----------------------------
ds = xr.open_dataset(SALIDA_NC)

# Nombre de variable puede ser 't2m'
var_name = "t2m" if "t2m" in ds.data_vars else list(ds.data_vars)[0]
da = ds[var_name]  # dims: time, latitude, longitude
# Escribir CRS y recortar con rioxarray
import rioxarray  # noqa: F401  (asegura registro del accessor)
da = da.rio.write_crs("EPSG:4326", inplace=True)

# Para recorte debemos pasar GeoJSON-like mapping
poly_mapping = [mapping(poly)]
da_clip = da.rio.clip(poly_mapping, crs="EPSG:4326")

# Kelvin -> °C
da_c = da_clip - 273.15
da_c.name = "t2m_c"

# Promedio espacial (sobre lat/lon) por hora
# Nota: dims suelen llamarse 'latitude', 'longitude' en ERA5
spatial_dims = [d for d in da_c.dims if d.lower() in ("latitude", "longitude", "lat", "lon")]
hora_series = da_c.mean(dim=spatial_dims).to_series()  # pandas Series indexada por time (UTC)

# -----------------------------
# 4) Convertir a hora local y preparar salida tabular
# -----------------------------
s_utc = hora_series.copy()
s_utc.index = pd.to_datetime(s_utc.index, utc=True)
s_local = s_utc.tz_convert(TZ_LOCAL)

df_out = pd.DataFrame({
    "time_local": s_local.index.tz_convert(TZ_LOCAL),
    "t2m_c": s_local.values
})
df_out["fecha_local"] = df_out["time_local"].dt.date
df_out["hora_local"] = df_out["time_local"].dt.strftime("%H:%M")

# Guardar CSV
df_out.to_csv(SALIDA_CSV, index=False)
print(f"[OK] Guardado {SALIDA_CSV}")

# -----------------------------
# 5) Métricas y gráfica
# -----------------------------
t_mean_day = df_out["t2m_c"].mean()
print(f"Promedio diario espacial (°C) para {DEPTO_AZUL}, {DIA}-{MES}-{ANIO}: {t_mean_day:.2f} °C")

plt.figure(figsize=(10, 4))
plt.plot(df_out["time_local"], df_out["t2m_c"])
plt.title(f"Temperatura 2 m (°C) por hora — {DEPTO_AZUL}, Bs.As. — {DIA}-{MES}-{ANIO}")
plt.xlabel(f"Hora ({TZ_LOCAL})")
plt.ylabel("Temperatura (°C)")
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig(SALIDA_FIG, dpi=150)
print(f"[OK] Gráfico guardado en {SALIDA_FIG}")
plt.show()
