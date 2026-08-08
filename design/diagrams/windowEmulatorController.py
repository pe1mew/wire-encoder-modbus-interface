"""Window-emulator controller schematic.

Renders design/diagrams/windowEmulatorController.png from the truth table in
design/windowEmulator.md §2.1, realised with two DPDT relays, two SPST-NC end
switches and two SPST-NO command switches.

    python design/diagrams/windowEmulatorController.py
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle, Circle, Polygon

BLK, RED, GRY = "#111111", "#b03030", "#7a7a7a"
LW, BLADE = 1.7, 2.6

fig, ax = plt.subplots(figsize=(15.2, 14.3))
ax.set_xlim(0, 16); ax.set_ylim(0, 15)
ax.set_aspect("equal"); ax.axis("off")
fig.patch.set_facecolor("white")


def wire(pts, c=BLK, lw=LW, ls="-", z=2):
    xs, ys = zip(*pts)
    ax.add_line(Line2D(xs, ys, color=c, lw=lw, ls=ls,
                       solid_capstyle="round", zorder=z))


def dot(x, y, c=BLK, r=0.06):
    ax.add_patch(Circle((x, y), r, color=c, zorder=6))


def txt(x, y, s, size=10, c=BLK, ha="center", va="center", weight="normal",
        style="normal"):
    ax.text(x, y, s, fontsize=size, color=c, ha=ha, va=va, zorder=7,
            fontweight=weight, fontstyle=style, linespacing=1.5)


def changeover(xc, yc, xt, yno, ync, tag):
    """Relay changeover drawn de-energised: blade from the common pivot
    resting on NC. Fixed contacts at xt, common pivot at xc."""
    stub = 0.34 if xt > xc else -0.34
    for yy, nm in ((yno, "NO"), (ync, "NC")):
        wire([(xt, yy), (xt - stub, yy)])
        dot(xt - stub, yy)
        txt(xt + (0.24 if xt > xc else -0.24), yy, nm, 9, GRY,
            ha="left" if xt > xc else "right")
    wire([(xc, yc), (xt - stub, ync)], lw=BLADE)      # blade -> NC
    ax.add_patch(Circle((xc, yc), 0.11, fc="white", ec=BLK, lw=LW, zorder=6))
    out = -0.32 if xt < xc else 0.32
    txt(xc + out, yc + 0.52, tag, 10, RED, weight="bold",
        ha="right" if xt < xc else "left")


def coil(x, ytop, ybot, name):
    w = 0.66
    ax.add_patch(Rectangle((x - w / 2, ybot), w, ytop - ybot, fill=False,
                           ec=BLK, lw=LW, zorder=3))
    txt(x + 0.60, (ytop + ybot) / 2, name, 12, RED, ha="left", weight="bold")


def spst(x, ytop, ybot, closed, name, sub):
    dot(x, ytop); dot(x, ybot)
    if closed:
        wire([(x, ybot), (x - 0.30, ytop - 0.06)], lw=BLADE)
        wire([(x - 0.44, ytop - 0.02), (x + 0.16, ytop - 0.02)])
    else:
        wire([(x, ybot), (x + 0.62, ytop + 0.10)], lw=BLADE)
        wire([(x - 0.22, ytop - 0.02), (x + 0.22, ytop - 0.02)])
    txt(x + 0.95, (ytop + ybot) / 2 + 0.20, name, 11, BLK, ha="left",
        weight="bold")
    txt(x + 0.95, (ytop + ybot) / 2 - 0.22, sub, 9, GRY, ha="left")


def diode(x, ya, yb, cath_b):
    """Vertical diode between ya and yb; cath_b puts the cathode bar at yb."""
    ym, s = (ya + yb) / 2, 0.19
    up = yb > ya
    tip = ym + (s if (up == cath_b) else -s)
    base = ym - (s if (up == cath_b) else -s)
    ax.add_patch(Polygon([(x - s, base), (x + s, base), (x, tip)],
                         closed=True, fc="white", ec=BLK, lw=LW, zorder=4))
    ax.add_line(Line2D([x - s * 1.15, x + s * 1.15], [tip, tip],
                       color=BLK, lw=LW + 0.3, zorder=5))
    wire([(x, ya), (x, base)]); wire([(x, tip), (x, yb)])


# ═══════════════════════════ power stage ═══════════════════════════
VD, GD = 13.40, 9.50
YNO, YCOM, YNC = 12.50, 11.40, 10.30
K1T, K1C = 5.20, 6.45
K2T, K2C = 11.00, 9.75
MX, MY, MR = 8.10, YCOM, 0.78

txt(8.0, 14.45, "POWER STAGE — two DPDT relays as a reversing bridge",
    14, BLK, weight="bold")
txt(8.0, 14.02, "contacts shown de-energised", 9.5, GRY, style="italic")

wire([(1.30, VD), (14.70, VD)]); wire([(1.30, GD), (14.70, GD)])
txt(1.05, VD, "+Vd", 12, BLK, ha="right", weight="bold")
txt(1.05, GD, "0Vd", 12, BLK, ha="right", weight="bold")

dot(2.30, VD); dot(3.35, VD)
wire([(2.30, VD), (3.24, VD + 0.50)], lw=BLADE)
txt(2.82, VD + 0.85, "E-STOP", 10.5, BLK, weight="bold")

for xt, xc, tag in ((K1T, K1C, "K1.A"), (K2T, K2C, "K2.A")):
    wire([(xt, VD), (xt, YNO)]); wire([(xt, YNC), (xt, GD)])
    dot(xt, VD); dot(xt, GD)
    changeover(xc, YCOM, xt, YNO, YNC, tag)

ax.add_patch(Circle((MX, MY), MR, fill=False, ec=BLK, lw=LW, zorder=3))
txt(MX, MY, "M", 17, BLK, weight="bold")
wire([(K1C, YCOM), (MX - MR, YCOM)]); wire([(MX + MR, YCOM), (K2C, YCOM)])
txt(7.05, YCOM - 0.40, "A", 10, GRY)
txt(9.15, YCOM - 0.40, "B", 10, GRY)

for x in (6.75, 9.45):
    dot(x, YCOM)
    diode(x, YCOM, VD, cath_b=True)
    diode(x, YCOM, GD, cath_b=False)
txt(8.10, 8.95, "four clamp diodes — one flyback across a reversing motor "
    "would short the supply one way round", 9.5, GRY, style="italic")

txt(1.35, 11.40, "pole B of each relay\nis spare — aux contacts\nfor "
    "indication and logging", 9.5, GRY, ha="left")

# ═══════════════════════════ coil stage ════════════════════════════
VL, GL = 7.90, 4.60
txt(8.0, 8.42, "COIL STAGE — end switch above the coil, command sinks below",
    14, BLK, weight="bold")

wire([(1.30, VL), (14.70, VL)]); wire([(1.30, GL), (14.70, GL)])
txt(1.05, VL, "+Vl", 12, BLK, ha="right", weight="bold")
txt(1.05, GL, "0V", 12, BLK, ha="right", weight="bold")

for x, k, endn, cmdn, act in ((K1T, "K1", "OpenEnd", "OPEN", "OPENS"),
                              (K2T, "K2", "CloseEnd", "CLOSE", "CLOSES")):
    dot(x, VL); dot(x, GL)
    wire([(x, VL), (x, 7.60)])
    spst(x, 7.60, 6.90, True, endn, "SPST N/C — opens at the end")
    wire([(x, 6.90), (x, 6.50)])
    coil(x, 6.50, 5.70, k)
    wire([(x, 5.70), (x, 5.30)])
    spst(x, 5.30, 4.60, False, cmdn, "SPST N/O — command, sinks to 0 V")
    dx = -1.15
    wire([(x, 6.50), (x + dx, 6.50)]); wire([(x, 5.70), (x + dx, 5.70)])
    diode(x + dx, 5.70, 6.50, cath_b=True)
    dot(x, 6.50); dot(x, 5.70)
    txt(x, 4.18, f"{k} energised  →  motor {'A' if k=='K1' else 'B'} to +Vd  "
        f"→  {act}", 10, RED, weight="bold")

# ═══════════════════════════ state table ═══════════════════════════
rows = [("0", "0", "·", "·", "off", "off", "0 V", "0 V", "braked"),
        ("1", "0", "0", "·", "ON", "off", "+V", "0 V", "OPENS"),
        ("1", "0", "1", "·", "off", "off", "0 V", "0 V", "braked"),
        ("0", "1", "·", "0", "off", "ON", "0 V", "+V", "CLOSES"),
        ("0", "1", "·", "1", "off", "off", "0 V", "0 V", "braked"),
        ("1", "1", "·", "·", "ON", "ON", "+V", "+V", "braked")]
hdr = ("Open", "Close", "OpenEnd", "CloseEnd", "K1", "K2", "A", "B", "motor")
cx = [0.85, 1.85, 3.00, 4.20, 5.20, 5.95, 6.75, 7.50, 8.55]
ytop = 3.45

for i, h in enumerate(hdr):
    txt(cx[i], ytop, h, 10, BLK, weight="bold")
wire([(0.55, ytop - 0.26), (9.10, ytop - 0.26)], lw=1.3)
wire([(4.72, ytop + 0.32), (4.72, 0.38)], lw=1.0, c=GRY)
for r, row in enumerate(rows):
    yy = ytop - 0.60 - r * 0.45
    for i, v in enumerate(row):
        em = v in ("ON", "OPENS", "CLOSES")
        txt(cx[i], yy, v, 10, RED if em else BLK,
            weight="bold" if em else "normal")
txt(0.55, 0.10, "All sixteen input combinations covered — the truth table needs "
    "no logic gates.", 9.5, GRY, ha="left", style="italic")

txt(9.75, ytop, "Why this topology", 11.5, BLK, ha="left", weight="bold")
notes = [
    ("Shoot-through is impossible.",
     "Each common reaches only one rail at a time."),
    ("Both stop states brake.",
     "All-off shorts the motor to 0Vd, both-on to +Vd."),
    ("End switch above the coil.",
     "A short to 0 V bypasses the command, not the inhibit."),
    ("N/C end switch.",
     "A cut conductor reads as 'at the end' and inhibits."),
]
yy = ytop - 0.60
for head, body in notes:
    txt(9.75, yy, head, 10, RED, ha="left", weight="bold")
    txt(9.75, yy - 0.34, body, 9.5, BLK, ha="left")
    yy -= 0.82

out = "design/diagrams/windowEmulatorController.png"
fig.savefig(out, dpi=165, bbox_inches="tight", pad_inches=0.30,
            facecolor="white")
print("wrote", out)
