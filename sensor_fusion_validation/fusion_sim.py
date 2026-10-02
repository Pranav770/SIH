"""
Module 2 - Multi-Sensor Fusion: illustrative simulation (not the EKF3 code).

Question it answers: what does each sensor buy us when GPS disappears indoors?
A linear Kalman filter per axis, state [position, velocity, accel_bias], IMU as
the prediction input, GPS (position) and optical flow (velocity) as updates.
EKF3 on the Pixhawk does the same job in full 3D with attitude, baro, mag.

Run:  python fusion_sim.py      -> writes ../assets/02-*.png
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from matplotlib.gridspec import GridSpec
import os

OUT = os.path.join(os.path.dirname(__file__), "..", "assets")
rng = np.random.default_rng(7)

# ---------------- scenario (illustrative numbers, not measured) -------------
DT, T = 0.02, 120.0                      # 50 Hz IMU, 120 s mission
GPS_HZ, FLOW_HZ = 5, 10
GPS_OFF_FROM = 45.0                      # drone enters the building
FLOW_LOST = (85.0, 100.0)                # featureless floor / smoke
ACC_BIAS, ACC_NOISE = 0.02, 0.05         # m/s^2
GPS_SIG, FLOW_SIG = 1.5, 0.10            # m, m/s

t = np.arange(0, T, DT)
tx = 12*np.sin(0.10*t); ty = 8*np.sin(0.05*t)
vx = 1.2*np.cos(0.10*t); vy = 0.4*np.cos(0.05*t)
ax = -0.12*np.sin(0.10*t); ay = -0.02*np.sin(0.05*t)
truth = np.stack([tx, ty], 1)

bias = np.array([ACC_BIAS, -0.7*ACC_BIAS])
imu = np.stack([ax, ay], 1) + bias + rng.normal(0, ACC_NOISE, (len(t), 2))

def run(use_gps, use_flow):
    est = np.zeros((len(t), 2)); sig = np.zeros(len(t)); vel = np.zeros((len(t), 2))
    F = np.array([[1, DT, -.5*DT**2], [0, 1, -DT], [0, 0, 1]])
    G = np.array([.5*DT**2, DT, 0.0])
    Q = ACC_NOISE**2*np.outer(G, G) + np.diag([0, 0, 1e-8])
    X = [np.array([0.0, vx[0], 0.0]), np.array([0.0, vy[0], 0.0])]
    P = [np.diag([0.1, 0.05, 0.05**2]) for _ in range(2)]
    for k in range(len(t)):
        for a in range(2):
            X[a] = F@X[a] + G*imu[k, a]; P[a] = F@P[a]@F.T + Q
        gps_ok = use_gps and t[k] < GPS_OFF_FROM and k % int(1/(GPS_HZ*DT)) == 0
        flow_ok = (use_flow and not (FLOW_LOST[0] <= t[k] < FLOW_LOST[1])
                   and k % int(1/(FLOW_HZ*DT)) == 0)
        for a, (tp, tv) in enumerate([(tx, vx), (ty, vy)]):
            for ok, H, z, r in [(gps_ok, [1, 0, 0], tp[k] + rng.normal(0, GPS_SIG), GPS_SIG),
                                (flow_ok, [0, 1, 0], tv[k] + rng.normal(0, FLOW_SIG), FLOW_SIG)]:
                if ok:
                    H = np.array(H); S = H@P[a]@H + r**2; K = P[a]@H/S
                    X[a] = X[a] + K*(z - H@X[a]); P[a] = P[a] - np.outer(K, H)@P[a]
        est[k] = [X[0][0], X[1][0]]; vel[k] = [X[0][1], X[1][1]]; sig[k] = 3*np.sqrt(P[0][0, 0] + P[1][1, 1])
    return est, sig, vel

cases = {"IMU only (dead reckoning)": run(False, False),
         "IMU + GPS": run(True, False),
         "IMU + GPS + optical flow": run(True, True)}
colors = ["#c0392b", "#e67e22", "#1e8449"]

# ---------------- figure 1: trajectories, error, availability ---------------
fig = plt.figure(figsize=(12, 7.5), constrained_layout=True)
gs = GridSpec(3, 2, figure=fig, height_ratios=[4, 4, 1])
a0 = fig.add_subplot(gs[:2, 0]); a1 = fig.add_subplot(gs[0, 1])
a2 = fig.add_subplot(gs[1, 1], sharex=a1); a3 = fig.add_subplot(gs[2, :])

a0.plot(*truth.T, "k--", lw=1.5, label="Ground truth")
for (name, (est, _, _)), c in zip(cases.items(), colors):
    m = np.abs(est).max(axis=1) < 60
    a0.plot(*est[m].T, color=c, lw=1.4, label=name)
i = int(GPS_OFF_FROM/DT)
a0.plot(*truth[i], "o", color="k"); a0.annotate("GPS lost\n(enters building)", truth[i],
        xytext=(truth[i][0]-14, truth[i][1]-14), arrowprops=dict(arrowstyle="->"))
a0.set_title("Estimated path (clipped to 60 m)"); a0.set_xlabel("x [m]"); a0.set_ylabel("y [m]")
a0.set_aspect("equal"); a0.legend(loc="lower left", fontsize=8); a0.grid(alpha=.3)

for (name, (est, sig, _)), c in zip(cases.items(), colors):
    err = np.linalg.norm(est - truth, axis=1)
    a1.semilogy(t, err, color=c, lw=1.4, label=name)
    if "flow" in name: a1.semilogy(t, sig, color=c, ls=":", lw=1.2, label="filter's own 3σ bound")
a1.set_ylabel("position error [m]"); a1.set_title("Position error (log scale)")
a1.legend(fontsize=7); a1.grid(alpha=.3, which="both")

for name, c in [("IMU + GPS", colors[1]), ("IMU + GPS + optical flow", colors[2])]:
    v = cases[name][2]
    a2.plot(t, np.linalg.norm(v - np.stack([vx, vy], 1), axis=1), color=c, lw=1.1, label=name)
a2.set_ylim(0, 0.6); a2.set_ylabel("velocity error [m/s]"); a2.set_title("Velocity error: flow bounds it, GPS-only cannot")
a2.legend(fontsize=7); a2.grid(alpha=.3)

for row, (lab, spans) in enumerate([("GPS", [(0, GPS_OFF_FROM)]), ("Optical flow", [(0, FLOW_LOST[0]), (FLOW_LOST[1], T)])]):
    for s, e in spans: a3.barh(row, e - s, left=s, color="#2e86c1", height=.6)
    a3.text(-2, row, lab, ha="right", va="center", fontsize=9)
a3.set_yticks([]); a3.set_xlim(0, T); a3.set_xlabel("time [s]"); a3.set_title("Sensor availability", fontsize=10)
fig.suptitle("Why fusion: what each sensor buys when GPS disappears (illustrative KF, per-axis)", fontsize=12)
fig.savefig(os.path.join(OUT, "02-gps-denied-fusion-sim.png"), dpi=140)

# ---------------- figure 2: architecture -----------------------------------
fig, ax = plt.subplots(figsize=(12, 5.2)); ax.axis("off"); ax.set_xlim(0, 12); ax.set_ylim(0, 5.2)
def box(x, y, w, h, text, fc, fs=9):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.04", fc=fc, ec="#333", lw=1.1))
    ax.text(x+w/2, y+h/2, text, ha="center", va="center", fontsize=fs)
def arrow(x1, y1, x2, y2, label=None):
    ax.annotate("", (x2, y2), (x1, y1), arrowprops=dict(arrowstyle="->", lw=1.2))
    if label: ax.text((x1+x2)/2, (y1+y2)/2+.12, label, ha="center", fontsize=7.5, color="#444")
ax.text(.1, 5.0, "Pixhawk 4 (flight controller)", fontsize=10, weight="bold")
ax.add_patch(FancyBboxPatch((.1, .3), 6.5, 4.5, boxstyle="round,pad=0.05", fc="#fdf6e3", ec="#b58900", lw=1.5))
box(.3, 3.7, 1.7, .75, "IMU\naccel + gyro", "#d6eaf8"); box(.3, 2.75, 1.7, .75, "Baro / Mag", "#d6eaf8")
box(.3, 1.8, 1.7, .75, "Downward LiDAR\nheight", "#d6eaf8"); box(.3, .85, 1.7, .75, "Optical flow\nX-Y rate", "#d6eaf8")
box(3.0, 2.0, 2.0, 1.6, "EKF3\npredict: IMU\nupdate: height, flow,\nGPS, mag", "#fadbd8", 9)
for y in (4.07, 3.12, 2.17, 1.22): arrow(2.0, y, 3.0, 2.8)
box(5.35, 2.35, 1.1, .9, "Pose\nvel + att", "#d5f5e3")
arrow(5.0, 2.8, 5.35, 2.8)
box(3.0, .45, 2.0, .7, "Source set switch\nGPS ↔ GPS-denied", "#fcf3cf", 8); arrow(4.0, 1.15, 4.0, 2.0)
box(7.6, 4.0, 1.6, .75, "GPS\n(outdoor only)", "#d6eaf8"); arrow(7.6, 4.37, 5.0, 3.4, "position, velocity")
box(7.6, 0.4, 1.6, .75, "2D LiDAR\non gimbal", "#d6eaf8")
box(7.6, 1.5, 1.6, .75, "RGB + thermal", "#d6eaf8")
box(9.9, 1.0, 1.9, 1.5, "Radxa Dragon Q6A\nYOLOv26n (NPU)\nRoom-level SLAM\nGeolocation", "#e8daef", 9)
arrow(9.2, 1.88, 9.9, 1.8, "frames"); arrow(9.2, .78, 9.9, 1.3, "scans")
arrow(6.45, 2.8, 9.9, 2.2, "MAVLink: pose, attitude")
box(9.9, 3.4, 1.9, .9, "Fused output\nposition + velocity +\ndetections → GeoJSON", "#d5f5e3", 8); arrow(10.85, 2.5, 10.85, 3.4)
ax.text(6, .05, "Level 1: state estimation (Pixhawk)    Level 2: source switching (GPS-denied)    Level 3: detection × pose fusion (Radxa)",
        ha="center", fontsize=8.5, style="italic")
fig.savefig(os.path.join(OUT, "02-fusion-architecture.png"), dpi=140, bbox_inches="tight")

# ---------------- figure 3: why pose quality matters for geotagging ---------
h = np.linspace(2, 30, 100)
fig, ax = plt.subplots(figsize=(7, 4.2))
for att, ls in [(0.5, "-"), (1.0, "--"), (2.0, ":")]:
    for off, c in [(0, "#1e8449"), (30, "#c0392b")]:
        e = np.sqrt(0.3**2 + (h*np.deg2rad(att)/np.cos(np.deg2rad(off))**2)**2)
        ax.plot(h, e, color=c, ls=ls, label=f"att err {att}°, off-nadir {off}°")
ax.set_xlabel("altitude above ground [m]"); ax.set_ylabel("victim geolocation error [m]")
ax.set_title("Detection geotag error ≈ √(σ_pos² + (h·σ_att / cos²θ)²)"); ax.legend(fontsize=7, ncol=2); ax.grid(alpha=.3)
fig.savefig(os.path.join(OUT, "02-geotag-error.png"), dpi=140, bbox_inches="tight")

# ---------------- console summary -------------------------------------------
for name, (est, sig, _) in cases.items():
    err = np.linalg.norm(est - truth, axis=1)
    print(f"{name:28s} err@45s={err[int(45/DT)]:7.2f} m  err@85s={err[int(85/DT)]:7.2f} m  err@120s={err[-1]:7.2f} m")
