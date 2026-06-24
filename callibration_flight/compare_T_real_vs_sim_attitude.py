#!/usr/bin/env python3
"""
Compare derived roll/pitch (mean + variability) between:
  - "This data": the real T* telemetry.csv from the LoRa avalanche UAV dataset
    (heading derived from GPS track / course-over-ground)
  - Simulated: the AirSim calibration flights (telemetry_20260413_*.csv)

Produces tables for means, standard deviations, Welch t-test / Levene / Mann-Whitney / KS
for both 'Giro' and 'Recta' segments ( |yaw_rate_deg| > 5 deg/s ).

Run from the callibration_flight/ directory or adjust paths.
"""

import pandas as pd
import numpy as np
from scipy import stats
from scipy.signal import savgol_filter
import glob
import os
import warnings
warnings.filterwarnings('ignore')

# ----------------- CONFIG -----------------
REAL_BASE = "dataset_using_UAVs/dataset"
SIM_GLOB = "telemetry_20260413_*.csv"
MANEUVER_YAW_RATE_THRESH_DEG_S = 5.0
G = 9.81
# ------------------------------------------

def latlon_to_local(df, lat_col='aircraftLatitude', lon_col='aircraftLongitude'):
    df = df.dropna(subset=[lat_col, lon_col]).copy()
    R = 6371000.0
    lat0 = df[lat_col].mean()
    lon0 = df[lon_col].mean()
    lat0_rad = np.radians(lat0)
    df['x_local'] = R * (np.radians(df[lon_col]) - np.radians(lon0)) * np.cos(lat0_rad)
    df['y_local'] = R * (np.radians(df[lat_col]) - np.radians(lat0))
    return df

def estimate_attitude_from_accel(df):
    psi = df['heading']
    a_bf = df['a_North'] * np.cos(psi) + df['a_East'] * np.sin(psi)
    a_bl = -df['a_North'] * np.sin(psi) + df['a_East'] * np.cos(psi)
    df['a_forward'] = a_bf
    df['a_lateral'] = a_bl
    df['est_pitch'] = -np.arctan2(a_bf, G) * 180.0 / np.pi
    df['est_roll']  =  np.arctan2(a_bl, G) * 180.0 / np.pi
    return df

def process_real_T(t_dir):
    """Process one T*/ telemetry.csv using track-derived heading."""
    tname = os.path.basename(t_dir)
    tel_path = os.path.join(t_dir, "telemetry.csv")
    if not os.path.exists(tel_path):
        tel_path = os.path.join(t_dir, "telemetry.txt")
    if not os.path.exists(tel_path):
        return None
    df = pd.read_csv(tel_path)
    df = df.rename(columns={
        'timestamp[ms]': 'timestamp_ms',
        'longitude': 'aircraftLongitude',
        'latitude': 'aircraftLatitude',
        'height[m]': 'height',
        'speed[m/s]': 'speed'
    })
    if 'timestamp_ms' not in df.columns:
        return None

    df = latlon_to_local(df, 'aircraftLatitude', 'aircraftLongitude')
    df['North'] = df['y_local']
    df['East'] = df['x_local']
    df['time_s'] = (df['timestamp_ms'] - df['timestamp_ms'].iloc[0]) / 1000.0

    # Smooth positions for stable course
    n = len(df)
    w = min(11, n - (1 if n % 2 == 0 else 2)) if n > 10 else 5
    if w >= 3:
        df['N_s'] = savgol_filter(df['North'], w, 2)
        df['E_s'] = savgol_filter(df['East'], w, 2)
    else:
        df['N_s'] = df['North']
        df['E_s'] = df['East']

    dN = np.gradient(df['N_s'], df['time_s'])
    dE = np.gradient(df['E_s'], df['time_s'])
    # course: 0 = North, increases clockwise to East
    course = np.arctan2(dE, dN)
    df['heading'] = course

    df['v_North'] = dN
    df['v_East'] = dE
    df['a_North'] = np.gradient(df['v_North'], df['time_s'])
    df['a_East'] = np.gradient(df['v_East'], df['time_s'])

    if w >= 5:
        df['a_North'] = savgol_filter(df['a_North'], min(9, w), 2)
        df['a_East'] = savgol_filter(df['a_East'], min(9, w), 2)

    df = estimate_attitude_from_accel(df)
    df['roll'] = df['est_roll']
    df['pitch'] = df['est_pitch']

    unw = np.unwrap(df['heading'])
    df['yaw_rate_deg'] = np.degrees(np.gradient(unw, df['time_s']))
    df['maneuver'] = np.where(df['yaw_rate_deg'].abs() > MANEUVER_YAW_RATE_THRESH_DEG_S, 'Giro', 'Recta')
    df['source_T'] = tname
    return df[['time_s', 'North', 'East', 'roll', 'pitch', 'yaw_rate_deg', 'maneuver', 'source_T']]

def process_sim_file(fpath):
    df = pd.read_csv(fpath)
    df['North'] = df['x']
    df['East'] = df['y']
    df['time_s'] = df['sim_t'] - df['sim_t'].iloc[0]
    df['a_North'] = np.gradient(df['vx'], df['time_s'])
    df['a_East'] = np.gradient(df['vy'], df['time_s'])
    df['heading'] = np.radians(df['yaw_deg'])
    df = estimate_attitude_from_accel(df)
    df['roll'] = df['est_roll']
    df['pitch'] = df['est_pitch']
    unw = np.unwrap(df['heading'])
    df['yaw_rate_deg'] = np.degrees(np.gradient(unw, df['time_s']))
    df['maneuver'] = np.where(df['yaw_rate_deg'].abs() > MANEUVER_YAW_RATE_THRESH_DEG_S, 'Giro', 'Recta')
    return df[['time_s', 'North', 'East', 'roll', 'pitch', 'yaw_rate_deg', 'maneuver']]

# ====================== MAIN ======================
print("Loading & processing real T* data (track-derived heading as proxy)...")
real_parts = []
for tdir in sorted(glob.glob(os.path.join(REAL_BASE, "T*"))):
    d = process_real_T(tdir)
    if d is not None and len(d) > 50:
        real_parts.append(d)
        print(f"  {os.path.basename(tdir)}: {len(d)} pts")

real = pd.concat(real_parts, ignore_index=True)
print(f"Total real T* points: {len(real)}")

print("\nLoading simulated calibration flights...")
sim_parts = []
for f in sorted(glob.glob(SIM_GLOB)):
    try:
        s = process_sim_file(f)
        sim_parts.append(s)
    except Exception as e:
        print("  skip", f, e)
sim = pd.concat(sim_parts, ignore_index=True)
print(f"Total sim points: {len(sim)}")

# ---- Descriptive ----
def desc(df, name):
    for m in ['Giro', 'Recta']:
        sub = df[df['maneuver'] == m]
        print(f"{name:12} {m:5} n={len(sub):7d}  "
              f"roll μ={sub['roll'].mean():+7.3f}° σ={sub['roll'].std():6.3f}   "
              f"pitch μ={sub['pitch'].mean():+7.3f}° σ={sub['pitch'].std():6.3f}")

print("\n" + "="*85)
print("DESCRIPTIVES")
print("="*85)
desc(real, "Real (T*)")
desc(sim, "Simulated")

# ---- Mean tests ----
print("\n" + "="*85)
print("MEAN DIFFERENCE TESTS (Welch + Mann-Whitney + Cohen d)")
print("="*85)

def mean_test(r, s, man, col):
    rr = r[r['maneuver']==man][col].dropna().values
    ss = s[s['maneuver']==man][col].dropna().values
    if len(rr) < 5 or len(ss) < 5:
        print(f"{man} {col}: insufficient n")
        return
    delta = rr.mean() - ss.mean()
    t, pw = stats.ttest_ind(rr, ss, equal_var=False)
    _, p_mw = stats.mannwhitneyu(rr, ss, alternative='two-sided')
    sd = np.sqrt((np.var(rr, ddof=1) + np.var(ss, ddof=1))/2)
    d = delta / sd if sd > 0 else 0.0
    print(f"{man:5} {col:5} | Δ={delta:+7.3f}°  Welch p={pw:.2e}  MWU p={p_mw:.2e}  d={d:6.3f}")

for man in ['Giro', 'Recta']:
    for col in ['roll', 'pitch']:
        mean_test(real, sim, man, col)

# ---- Variance tests (Levene) ----
print("\n" + "="*85)
print("VARIANCE DIFFERENCE TESTS (Levene)")
print("="*85)

for man in ['Giro', 'Recta']:
    for col in ['roll', 'pitch']:
        rr = real[real['maneuver']==man][col].dropna().values
        ss = sim[sim['maneuver']==man][col].dropna().values
        stat, p = stats.levene(rr, ss)
        print(f"{man:5} {col:5} | Levene stat={stat:8.3f}  p={p:.2e}  {'***' if p < 0.001 else ('**' if p < 0.01 else ('*' if p < 0.05 else ''))}")

# ---- Save summary ----
summary = []
for name, df_ in [('Real_T*', real), ('Sim', sim)]:
    for man in ['Giro', 'Recta']:
        sub = df_[df_['maneuver'] == man]
        summary.append({
            'dataset': name,
            'maneuver': man,
            'n': len(sub),
            'roll_mean': sub['roll'].mean(),
            'roll_std': sub['roll'].std(),
            'pitch_mean': sub['pitch'].mean(),
            'pitch_std': sub['pitch'].std(),
        })
pd.DataFrame(summary).round(4).to_csv("attitude_comparison_Treal_vs_sim_summary.csv", index=False)
print("\nSaved summary to attitude_comparison_Treal_vs_sim_summary.csv")

print("\nDone. Note: Real heading derived from GPS track (no explicit heading in these T* logs).")
