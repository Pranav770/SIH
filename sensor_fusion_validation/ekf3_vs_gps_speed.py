"""Plot raw GPS speed against the onboard EKF3 speed for the two flights in the third log.
Usage: python ekf3_vs_gps_speed.py path/to/log.bin   -> ../assets/06-ekf3-vs-gps-speed.png"""
import sys, os, numpy as np
from pymavlink import mavutil
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
LOG = sys.argv[1] if len(sys.argv) > 1 else sys.exit("usage: python " + os.path.basename(__file__) + " path/to/log.bin")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
G, E, T = [], [], []
m = mavutil.mavlink_connection(LOG, dialect="ardupilotmega")
while (x := m.recv_match(type=["GPS", "XKF1", "XKF4"])) is not None:
    d = x.to_dict(); t = d["TimeUS"]/1e6
    if x.get_type() == "GPS": G.append((t, d["Spd"]))
    elif d["C"] == 0 and x.get_type() == "XKF1": E.append((t, np.hypot(d["VN"], d["VE"])))
    elif d["C"] == 0: T.append((t, d["SV"]))
G, E, T = map(np.array, (G, E, T))
fig, ax = plt.subplots(2, 2, figsize=(12, 6), sharex="col", constrained_layout=True)
for col, (name, (a, b)) in enumerate({"Flight A": (84, 224), "Flight B": (398, 473)}.items()):
    for arr, ax_, kw in [(G, ax[0, col], dict(color="#aaa", label="raw GPS speed")), (E, ax[0, col], dict(color="#2e86c1", lw=1.6, label="Pixhawk EKF3 speed"))]:
        s = (arr[:, 0] >= a) & (arr[:, 0] <= b); ax_.plot(arr[s, 0], arr[s, 1], **kw)
    s = (T[:, 0] >= a) & (T[:, 0] <= b); ax[1, col].plot(T[s, 0], T[s, 1], color="#8e44ad"); ax[1, col].axhline(1, color="r", ls="--", lw=.8)
    ax[0, col].set_title(name); ax[0, col].set_ylabel("speed [m/s]"); ax[1, col].set_ylabel("GPS trust test\n(above 1 = ignored)"); ax[1, col].set_xlabel("log time [s]")
    ax[0, col].grid(alpha=.3); ax[1, col].grid(alpha=.3)
ax[0, 0].legend(fontsize=8)
fig.suptitle("Real flights with weak GPS: the Pixhawk fusion ignores GPS speed spikes")
fig.savefig(os.path.join(OUT, "06-ekf3-vs-gps-speed.png"), dpi=140)
