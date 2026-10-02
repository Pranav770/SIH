"""
Module 2 - Offline sensor-fusion replay on a real ArduPilot log (log_0, Pixhawk 4, ArduCopter 4.7.1).

Usage:  python fusion_replay.py path/to/log.bin   -> ../assets/04-*.png + printed summary
Needs:  pymavlink numpy scipy matplotlib

Three things are done on the logged data:
  A. Sensor audit: which sensors actually delivered usable data (GPS, rangefinder, baro, optical flow).
  B. Vertical fusion: IMU + baro + rangefinder in one filter, compared with the onboard EKF3 height.
  C. Horizontal fusion: IMU + GPS in one filter, then GPS is removed for 5/10/20 s at many moments in
     the flight to measure how fast position drifts without an aiding source.
The filters are simple per-axis Kalman filters for teaching and analysis; they are not EKF3.
"""
import sys, os
import numpy as np
from pymavlink import mavutil
from scipy.spatial.transform import Rotation as Rot
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

LOG = sys.argv[1] if len(sys.argv) > 1 else sys.exit("usage: python " + os.path.basename(__file__) + " path/to/log.bin")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
REST = (185.0, 200.0)            # on the ground, motors off: used to calibrate IMU bias
FLY = (208.0, 276.0)             # throttle active (found from CTUN.ThO)

# ---------------------------------------------------------------- load
FIELDS = {"GPS": ["Status","NSats","Lat","Lng","Spd","GCrs"], "OF": ["Qual","flowX","flowY"],
          "RFND": ["Dist","Stat"], "XKF1": ["C","Roll","Pitch","Yaw","PD"],
          "IMU": ["I","AccX","AccY","AccZ"], "CTUN": ["ThO","Alt","BAlt","SAlt"], "ORGN": ["Lat","Lng"]}
D = {k: {f: [] for f in ["t"] + v} for k, v in FIELDS.items()}
m = mavutil.mavlink_connection(LOG, dialect="ardupilotmega")
while (x := m.recv_match()) is not None:
    k = x.get_type()
    if k in D:
        d = x.to_dict(); D[k]["t"].append(d["TimeUS"] / 1e6)
        for f in FIELDS[k]: D[k][f].append(d[f])
D = {k: {f: np.array(v) for f, v in d.items()} for k, d in D.items()}
g, o, r, xk, imu, c = D["GPS"], D["OF"], D["RFND"], D["XKF1"], D["IMU"], D["CTUN"]
lat0, lng0 = D["ORGN"]["Lat"][0], D["ORGN"]["Lng"][0]
gps_ne = np.stack([(g["Lat"]-lat0)*111320.0, (g["Lng"]-lng0)*111320.0*np.cos(np.deg2rad(lat0))], 1)
gps_v = np.stack([g["Spd"]*np.cos(np.deg2rad(g["GCrs"])), g["Spd"]*np.sin(np.deg2rad(g["GCrs"]))], 1)
k0 = xk["C"] == 0; tx = xk["t"][k0]
i0 = imu["I"] == 0; ti = imu["t"][i0]
acc_b = np.stack([imu["AccX"][i0], imu["AccY"][i0], imu["AccZ"][i0]], 1)
eul = np.stack([np.interp(ti, tx, np.unwrap(np.deg2rad(xk[a][k0]))) for a in ("Yaw", "Pitch", "Roll")], 1)
a_ned = Rot.from_euler("ZYX", eul).apply(acc_b) + np.array([0, 0, 9.80665])
rest = (ti > REST[0]) & (ti < REST[1]); a_bias = a_ned[rest].mean(0)
a_ne, a_up = a_ned[:, :2] - a_bias[:2], -(a_ned[:, 2] - a_bias[2])

# ---------------------------------------------------------------- A. sensor audit
fly_of = (o["t"] > FLY[0]) & (o["t"] < FLY[1])
print(f"[audit] flow quality > 0 : {np.mean(o['Qual']>0)*100:.1f}% of all samples; raw flow non-zero in flight: "
      f"{np.mean((o['flowX'][fly_of]!=0)|(o['flowY'][fly_of]!=0))*100:.1f}%")
fly_r = (r["t"] > FLY[0]) & (r["t"] < FLY[1])
print(f"[audit] rangefinder status Good in flight: {np.mean(r['Stat'][fly_r]==4)*100:.0f}%; max reading {r['Dist'][fly_r].max():.2f} m")
print(f"[audit] GPS fix type 4 for {np.mean(g['Status']==4)*100:.0f}% of samples, sats {int(g['NSats'].min())}-{int(g['NSats'].max())}")

fig, ax = plt.subplots(5, 1, figsize=(11, 10), sharex=True, constrained_layout=True)
ax[0].plot(c["t"], c["ThO"], "k"); ax[0].set_ylabel("throttle out")
ax[1].plot(g["t"], g["Spd"], color="#2e86c1"); ax[1].set_ylabel("GPS speed [m/s]")
good = np.where(r["Stat"] == 4, r["Dist"], np.nan)
ax[2].plot(r["t"], r["Dist"], color="#bbb", lw=.8, label="all readings"); ax[2].plot(r["t"], good, color="#1e8449", label="status Good")
ax[2].set_ylabel("rangefinder [m]"); ax[2].legend(fontsize=7)
ax[3].plot(o["t"], o["Qual"], color="#c0392b"); ax[3].set_ylabel("flow quality (0-255)"); ax[3].set_ylim(-5, 260)
ax[3].text(0.01, 0.55, "quality = 0 for the entire log", transform=ax[3].transAxes, color="#c0392b")
ax[4].plot(o["t"], np.hypot(o["flowX"], o["flowY"]), color="#8e44ad", lw=.6); ax[4].set_ylabel("raw flow rate [rad/s]")
for a in ax: a.axvspan(*FLY, color="#f9e79f", alpha=.35); a.grid(alpha=.3)
ax[4].set_xlabel("log time [s]"); fig.suptitle("log_0: what each sensor delivered (shaded = flight)")
fig.savefig(os.path.join(OUT, "04-log0-sensor-audit.png"), dpi=140)

# ---------------------------------------------------------------- B. vertical fusion
def vertical(use_rng):
    sel = (ti >= REST[0]) & (ti <= FLY[1] + 4); idx = np.where(sel)[0]
    baro = np.interp(ti, c["t"], c["BAlt"]); b0 = baro[rest].mean(); baro = baro - b0
    rng = np.interp(ti, r["t"], np.where((r["Stat"] == 4) & (r["Dist"] < 4.9) & (r["Dist"] > 0.2), r["Dist"], np.nan))
    X = np.zeros(3); P = np.diag([.5, .1, .05**2]); out = np.zeros(len(idx)); tp = ti[idx[0]]
    for n, k in enumerate(idx):
        dt = ti[k] - tp; tp = ti[k]
        if dt > 0:
            F = np.array([[1, dt, -.5*dt*dt], [0, 1, -dt], [0, 0, 1]]); G = np.array([.5*dt*dt, dt, 0])
            X = F@X + G*a_up[k]; P = F@P@F.T + 0.5**2*np.outer(G, G) + np.diag([0, 0, 1e-6*dt])
        for ok, z, rr in [(True, baro[k], 1.0), (use_rng and np.isfinite(rng[k]), rng[k], 0.15)]:
            if ok:
                H = np.array([1., 0, 0]); S = H@P@H + rr**2; K = P@H/S; X = X + K*(z - H@X); P = P - np.outer(K, H)@P
        out[n] = X[0]
    return ti[idx], out
tz, z_baro = vertical(False); _, z_fused = vertical(True)
ekf_alt = np.interp(tz, c["t"], c["Alt"]); rng_alt = np.interp(tz, c["t"], c["SAlt"])
fv = (tz > FLY[0]) & (tz < FLY[1]) & np.isfinite(rng_alt) & (np.interp(tz, r["t"], r["Dist"]) < 4.9) & (np.interp(tz, r["t"], r["Stat"]) == 4)
rms = lambda a: np.sqrt(np.mean((a[fv]-rng_alt[fv])**2))
print(f"[vertical] RMS height difference to rangefinder (valid, <4.9 m): onboard EKF3 {rms(ekf_alt):.2f} m | "
      f"baro+IMU {rms(z_baro):.2f} m | baro+IMU+rangefinder {rms(z_fused):.2f} m (circular: it uses the rangefinder) | peak EKF3-vs-rangefinder {np.abs(ekf_alt-rng_alt)[fv].max():.2f} m")
fig, ax = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True, constrained_layout=True)
ax[0].plot(tz, rng_alt, color="#1e8449", lw=1, label="rangefinder (tilt-corrected)")
ax[0].plot(tz, ekf_alt, color="#2e86c1", lw=1.4, label="onboard EKF3 height (baro-based)")
ax[0].plot(tz, z_baro, color="#e67e22", lw=1, ls="--", label="offline: IMU + baro")
ax[0].plot(tz, z_fused, color="#c0392b", lw=1.4, label="offline: IMU + baro + rangefinder")
ax[0].set_ylabel("height [m]"); ax[0].legend(fontsize=8, loc="upper left"); ax[0].set_xlim(FLY[0]-5, FLY[1]+4); ax[0].grid(alpha=.3)
ax[1].plot(tz, ekf_alt-rng_alt, color="#2e86c1", label="EKF3 minus rangefinder")
ax[1].plot(tz, z_fused-rng_alt, color="#c0392b", label="fused minus rangefinder (small by construction)"); ax[1].axhline(0, color="k", lw=.5)
ax[1].set_ylabel("difference [m]"); ax[1].set_xlabel("log time [s]"); ax[1].legend(fontsize=8); ax[1].grid(alpha=.3)
fig.suptitle("Vertical channel: three height sources disagree, fusion can reconcile them")
fig.savefig(os.path.join(OUT, "04-log0-height-fusion.png"), dpi=140)

# ---------------------------------------------------------------- C. horizontal fusion + GPS dropouts
bias0 = np.zeros(2)  # bias already removed from a_ne using the ground-rest window
def run(t0, t1, gaps=()):
    idx = np.where((ti >= t0) & (ti <= t1))[0]; gi = np.searchsorted(g["t"], t0)
    X = np.zeros((2, 3)); X[:, 0] = gps_ne[gi]; X[:, 1] = gps_v[gi]
    P = [np.diag([1., .1, .05**2]) for _ in range(2)]; est = []; tt = []; tp = ti[idx[0]]
    for k in idx:
        dt = ti[k] - tp; tp = ti[k]
        if dt <= 0: continue
        F = np.array([[1, dt, -.5*dt*dt], [0, 1, -dt], [0, 0, 1]]); G = np.array([.5*dt*dt, dt, 0])
        Q = 0.4**2*np.outer(G, G) + np.diag([0, 0, 2e-6*dt])
        for a in range(2): X[a] = F@X[a] + G*a_ne[k, a]; P[a] = F@P[a]@F.T + Q
        while gi < len(g["t"]) and g["t"][gi] <= ti[k]:
            if not any(a0 <= g["t"][gi] < a1 for a0, a1 in gaps):
                for a in range(2):
                    for H, z, rr in [([1, 0, 0], gps_ne[gi, a], 1.5), ([0, 1, 0], gps_v[gi, a], .3)]:
                        H = np.array(H); S = H@P[a]@H + rr**2; K = P[a]@H/S; X[a] = X[a] + K*(z - H@X[a]); P[a] = P[a] - np.outer(K, H)@P[a]
            gi += 1
        est.append(X[:, 0].copy()); tt.append(ti[k])
    return np.array(tt), np.array(est)
ref = lambda tt: np.stack([np.interp(tt, g["t"], gps_ne[:, a]) for a in range(2)], 1)

t_full, e_full = run(FLY[0]-5, FLY[1], ())
print(f"[horizontal] IMU+GPS filter vs GPS track: mean diff {np.linalg.norm(e_full-ref(t_full),axis=1).mean():.2f} m (GPS noise ~1 m)")
durs = [5, 10, 20]; starts = np.arange(215, 252, 4); res = {d: [] for d in durs}
for d in durs:
    for s0 in starts:
        tt, e = run(s0-8, s0+d, [(s0, s0+d)]); res[d].append(np.linalg.norm(e[-1]-ref(tt[-1:])[0]))
for d in durs: print(f"[dropout {d:2d}s] error at end of outage over {len(starts)} start times: median {np.median(res[d]):.1f} m, worst {np.max(res[d]):.1f} m")

s0, d = 232, 20; tt, e = run(s0-8, s0+d+6, [(s0, s0+d)])
fig, ax = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
sel = (g["t"] >= s0-8) & (g["t"] <= s0+d+6); ax[0].plot(gps_ne[sel, 1], gps_ne[sel, 0], "k--", label="GPS track")
ax[0].plot(e[:, 1], e[:, 0], color="#c0392b", label=f"IMU+GPS filter, GPS removed {s0}-{s0+d} s")
j = np.searchsorted(tt, s0); ax[0].plot(e[j, 1], e[j, 0], "o", color="#c0392b"); ax[0].set_aspect("equal"); ax[0].grid(alpha=.3)
ax[0].set_xlabel("East [m]"); ax[0].set_ylabel("North [m]"); ax[0].legend(fontsize=8); ax[0].set_title("One example outage (20 s)")
ax[1].boxplot([res[x] for x in durs], tick_labels=[f"{x} s" for x in durs]); ax[1].set_xlabel("GPS outage length"); ax[1].set_ylabel("position error at end of outage [m]")
ax[1].set_title(f"{len(starts)} outages at different moments of the flight"); ax[1].grid(alpha=.3)
fig.suptitle("Real data: how fast position drifts with no aiding source")
fig.savefig(os.path.join(OUT, "04-log0-gps-outage.png"), dpi=140)
