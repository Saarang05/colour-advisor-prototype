"""
Colour-correction advisor: a synthetic demo.

WHAT THIS PROVES (and what it does not)
---------------------------------------
Point being tested: if you MEASURE the colour difference of a production tile
against the master (in Lab), and you have even a rough model of how the print
channels change the fired colour, you can compute the change to make to the
print file instead of guessing. Each physical print-fire-measure round then
gets closer, so fewer rounds and fewer variants are needed.

This is a SIMULATION. The "printer + glaze + kiln" is an invented stand-in
function, not the client's process. So the numbers show how the method behaves
under stated assumptions. They do NOT prove it will work on real tiles. That
is what the pilot is for.

HOW IT WORKS
------------
* A SKU has 4 colour zones. Each zone has a print recipe (coverage % of 6 inks).
* The master tile is the colour that recipe gives with no drift.
* On a new production run the process has drifted: each ink prints a bit
  stronger or weaker (random, up to about +/-12%), and the kiln adds a small
  overall shift. Nobody knows these numbers.
* The only thing we can do is change the file: one gain per ink channel
  (like "brown +4%"). Then print, fire, measure with a spectrophotometer
  (which has some measurement noise).
* MANUAL strategy (imitates today's loop): the QC engineer looks at the
  differences, picks the 3 channels that look most responsible using a rough
  mental model, prints 6 variants (3 channels x 2 step sizes), and keeps the
  best. Repeat.
* ADVISOR strategy: uses a model of how each channel moves Lab (a sensitivity
  matrix, with some error because it is learned from history), solves for the
  channel changes that cancel the measured difference, prints 3 candidates
  (70%, 100%, 130% of the suggested change), keeps the best, and updates its
  model from what it just measured. Repeat.
* "Accepted" = average colour difference over the zones, measured, is at or
  below TOL (CIEDE2000). Both strategies must reach it.

Run:  python simulate.py            (about 1 minute)
"""
import argparse
import csv
import os

import numpy as np
from scipy.optimize import minimize
from skimage.color import deltaE_ciede2000

N_INK = 6
N_ZONE = 4
TOL = 1.0            # accept when mean zone dE2000 <= 1.0 (an assumption, client sets the real one)
MAX_ROUNDS = 8       # give up after 8 physical rounds
U_LIMIT = 0.35       # never change a channel by more than about +/-35% in total
DRIFT_SD = 0.20      # process drift: ink strength varies by about 20% (1 std dev)
KILN_SD_L = 1.5      # kiln shift in L (lightness), 1 std dev
KILN_SD_B = 1.0      # kiln shift in b, 1 std dev
# These three were raised from first-draft values (0.12 / 1.0 / 0.8) because the
# first draft started with a median error of only dE 1.7, too small to look like a
# real shade problem. They were set from the START error, not from the results.

# Rough Lab direction of each ink at full strength (invented, plausible-looking)
DIRS = np.array([
    [-20, -15, -12],   # cyan-like
    [-18, 20, 10],     # magenta-like
    [-10, 5, 30],      # yellow-like
    [-30, 2, 4],       # black-like
    [-22, 14, 22],     # brown-like
    [-12, -8, 6],      # grey-like
], dtype=float)
TAU = 45.0


def lab_from_ink(ink):
    """Stand-in for printer + glaze + kiln. ink: (..., 6) coverage in % -> Lab (..., 3).
    Saturating response per ink, plus a small 'inks together darken more' term."""
    h = 1.0 - np.exp(-ink / TAU)
    lab = np.array([92.0, 0.0, 0.0]) + h @ DIRS
    lab[..., 0] = lab[..., 0] - 0.8 * h.sum(-1) ** 2
    return lab


class Event:
    """One changeover: one SKU, one unknown process drift."""

    def __init__(self, rng, sigma):
        self.rng = rng
        self.sigma = sigma  # measurement noise (Lab units, per coordinate)
        # Recipes: 2-3 strong inks per zone, the rest weak
        rec = rng.uniform(0, 8, size=(N_ZONE, N_INK))
        for z in range(N_ZONE):
            strong = rng.choice(N_INK, size=rng.integers(2, 4), replace=False)
            rec[z, strong] = rng.uniform(15, 70, size=len(strong))
        self.recipe = rec
        self.master_true = lab_from_ink(rec)
        self.drift = rng.normal(0, DRIFT_SD, size=N_INK)          # log ink strength drift
        self.kiln = np.array([rng.normal(0, KILN_SD_L), 0.0, rng.normal(0, KILN_SD_B)])
        # master measured once, with noise
        self.master_meas = self.master_true + rng.normal(0, sigma, self.master_true.shape)

    def prod_true(self, u):
        """True fired colour of production tile when the file is changed by log-gains u."""
        return lab_from_ink(self.recipe * np.exp(u + self.drift)) + self.kiln

    def measure(self, u):
        """What the spectrophotometer reports (noisy), as difference to the measured master."""
        m = self.prod_true(u) + self.rng.normal(0, self.sigma, self.master_true.shape)
        return (m - self.master_meas).ravel()

    def mean_de_true(self, u):
        return float(deltaE_ciede2000(self.prod_true(u), self.master_true).mean())

    def best_achievable_de(self):
        """The best true dE2000 that ANY change of the 6 channels (within the limit) can reach.
        Some differences (e.g. a kiln shift) cannot be cancelled by editing the file, so
        this is a floor. Real life cannot compute it exactly; the advisor estimates it."""
        f = lambda u: float(deltaE_ciede2000(self.prod_true(u), self.master_true).mean())
        best = np.inf
        for k in range(4):
            x0 = np.random.default_rng(k).uniform(-0.1, 0.1, N_INK)
            r = minimize(f, x0, bounds=[(-U_LIMIT, U_LIMIT)] * N_INK, method="L-BFGS-B")
            best = min(best, r.fun)
        return best

    def true_jacobian(self, u, eps=1e-3):
        """d(difference)/d(log gain) at u, by finite differences (12 x 6)."""
        base = self.prod_true(u).ravel()
        J = np.zeros((N_ZONE * 3, N_INK))
        for c in range(N_INK):
            u2 = u.copy()
            u2[c] += eps
            J[:, c] = (self.prod_true(u2).ravel() - base) / eps
        return J


def de_from_y(y, ev):
    """Mean dE2000 implied by a measured difference vector y (12,)."""
    prod_meas = y.reshape(N_ZONE, 3) + ev.master_meas
    return float(deltaE_ciede2000(prod_meas, ev.master_meas).mean())


def solve_change(J, y):
    """Channel changes du that cancel the measured difference y, with a small
    ridge penalty (so we do not make wild changes) and a hard limit."""
    JTJ = J.T @ J
    lam = 0.05 * np.trace(JTJ) / N_INK
    du = np.linalg.solve(JTJ + lam * np.eye(N_INK), -J.T @ y)
    return np.clip(du, -U_LIMIT, U_LIMIT)


def run_manual(ev, rng, human_err):
    """Today's loop: rough mental model, 6 single-channel variants per round."""
    u = np.zeros(N_INK)
    J0 = ev.true_jacobian(u)
    Jh = J0 * (1 + human_err * rng.standard_normal(J0.shape))  # the engineer's rough mental model
    y = ev.measure(u)
    rounds = 0
    while de_from_y(y, ev) > TOL and rounds < MAX_ROUNDS:
        rounds += 1
        # Which channels look most responsible? Direction and benefit per channel.
        proj = Jh.T @ y
        benefit = np.abs(proj) / (np.linalg.norm(Jh, axis=0) + 1e-9)
        top = np.argsort(-benefit)[:3]
        cands = []
        for c in top:
            sgn = -np.sign(proj[c])
            for step in (0.04, 0.08):
                v = u.copy()
                v[c] += sgn * step
                cands.append(v)
        best_u, best_y, best_de = u, y, de_from_y(y, ev)
        for v in cands:
            yv = ev.measure(v)
            d = de_from_y(yv, ev)
            if d < best_de:
                best_u, best_y, best_de = v, yv, d
        u, y = best_u, best_y
    return u, rounds, rounds * 6, de_from_y(y, ev) <= TOL


def run_expert(ev, rng, human_err):
    """An OPTIMISTIC manual loop: the engineer can do the sums by eye (combined change across
    channels, 6 variants at different strengths), but the mental model is never updated from
    what the lab measures. Together with run_manual (crude) this brackets real QC practice,
    which we have NOT measured. The pilot measures it from the client's own lab logs."""
    u = np.zeros(N_INK)
    J0 = ev.true_jacobian(u)
    Jh = J0 * (1 + human_err * rng.standard_normal(J0.shape))
    y = ev.measure(u)
    rounds = 0
    while de_from_y(y, ev) > TOL and rounds < MAX_ROUNDS:
        rounds += 1
        du = solve_change(Jh, y)
        best_u, best_y, best_de = u, y, de_from_y(y, ev)
        for s in (0.4, 0.6, 0.8, 1.0, 1.2, 1.4):
            v = np.clip(u + s * du, -U_LIMIT, U_LIMIT)
            yv = ev.measure(v)
            d = de_from_y(yv, ev)
            if d < best_de:
                best_u, best_y, best_de = v, yv, d
        u, y = best_u, best_y
    return u, rounds, rounds * 6, de_from_y(y, ev) <= TOL


def run_advisor(ev, rng, prior_err):
    """Advisor: model-based change, 3 candidates per round, model updated from measurements."""
    u = np.zeros(N_INK)
    J0 = ev.true_jacobian(u)
    Jhat = J0 * (1 + prior_err * rng.standard_normal(J0.shape))  # imperfect model learned from history
    y = ev.measure(u)
    rounds = 0
    while de_from_y(y, ev) > TOL and rounds < MAX_ROUNDS:
        rounds += 1
        du = solve_change(Jhat, y)
        best_u, best_y, best_de = u, y, de_from_y(y, ev)
        for s in (0.7, 1.0, 1.3):
            v = np.clip(u + s * du, -U_LIMIT, U_LIMIT)
            yv = ev.measure(v)
            dg, dy = v - u, yv - y
            if dg @ dg > 1e-12:  # secant update of the model from what we just saw
                Jhat = Jhat + 0.5 * np.outer(dy - Jhat @ dg, dg) / (dg @ dg)
            d = de_from_y(yv, ev)
            if d < best_de:
                best_u, best_y, best_de = v, yv, d
        u, y = best_u, best_y
    return u, rounds, rounds * 3, de_from_y(y, ev) <= TOL


def run_scenario(n_events, seed, sigma, human_err, prior_err, with_floor=False):
    out = {"manual": [], "advisor": [], "expert": []}
    start_de = []
    floors = []
    for i in range(n_events):
        rng_env = np.random.default_rng([seed, i, 1])
        ev_m = Event(rng_env, sigma)
        # Same drift for both strategies: copy the event, separate noise streams
        ev_a = Event(np.random.default_rng([seed, i, 1]), sigma)
        ev_m.rng = np.random.default_rng([seed, i, 2])
        ev_a.rng = np.random.default_rng([seed, i, 3])
        start_de.append(ev_m.mean_de_true(np.zeros(N_INK)))
        if with_floor:
            floors.append(ev_m.best_achievable_de())
        u, r, nv, ok = run_manual(ev_m, np.random.default_rng([seed, i, 4]), human_err)
        out["manual"].append((r, nv, ok, ev_m.mean_de_true(u)))
        u, r, nv, ok = run_advisor(ev_a, np.random.default_rng([seed, i, 5]), prior_err)
        out["advisor"].append((r, nv, ok, ev_a.mean_de_true(u)))
        if with_floor:  # the optimistic manual loop is only run for the headline scenario
            ev_e = Event(np.random.default_rng([seed, i, 1]), sigma)
            ev_e.rng = np.random.default_rng([seed, i, 6])
            u, r, nv, ok = run_expert(ev_e, np.random.default_rng([seed, i, 7]), 0.3)
            out["expert"].append((r, nv, ok, ev_e.mean_de_true(u)))
    return out, np.array(start_de), np.array(floors)


def summarise(rows, mask=None):
    if mask is not None:
        rows = [x for x, keep in zip(rows, mask) if keep]
    r = np.array([x[0] for x in rows])
    nv = np.array([x[1] for x in rows])
    ok = np.array([x[2] for x in rows])
    de = np.array([x[3] for x in rows])
    return {
        "median_rounds": float(np.median(r)),
        "within_1_round_pct": 100 * float(np.mean(ok & (r <= 1))),
        "within_2_rounds_pct": 100 * float(np.mean(ok & (r <= 2))),
        "not_accepted_pct": 100 * float(np.mean(~ok)),
        "median_variants": float(np.median(nv)),
        "median_true_dE_final": float(np.median(de)),
        "false_accept_pct": 100 * float(np.mean(ok & (de > TOL + 0.5))),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--outdir", default="results")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)

    # Headline settings (chosen BEFORE running, not tuned afterwards)
    SIGMA, HUMAN_ERR, PRIOR_ERR = 0.15, 0.5, 0.25
    head, start_de, floors = run_scenario(a.events, a.seed, SIGMA, HUMAN_ERR, PRIOR_ERR, with_floor=True)
    sm, sa, se = summarise(head["manual"]), summarise(head["advisor"]), summarise(head["expert"])
    fixable = floors <= 0.7     # events where a file change CAN get comfortably inside tolerance
    sm_fix, sa_fix = summarise(head["manual"], fixable), summarise(head["advisor"], fixable)
    se_fix = summarise(head["expert"], fixable)
    share_unfixable = 100 * float(np.mean(floors > TOL))

    # Sensitivity: how bad can the measurement noise and the starting model be?
    sens = []
    for sigma in (0.05, 0.15, 0.30, 0.60):
        for prior in (0.15, 0.25, 0.5, 1.0):
            res, _, _ = run_scenario(a.events, a.seed, sigma, HUMAN_ERR, prior)
            m, ad = summarise(res["manual"]), summarise(res["advisor"])
            sens.append({"noise_sd_lab": sigma, "model_error": prior,
                         **{"advisor_" + k: v for k, v in ad.items()},
                         **{"manual_" + k: v for k, v in m.items()}})

    with open(os.path.join(a.outdir, "sensitivity.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(sens[0].keys()))
        w.writeheader()
        w.writerows(sens)

    lines = []
    lines.append("# Synthetic results (invented process, not client data)\n")
    lines.append(f"{a.events} simulated changeovers, seed {a.seed}. Accept at mean dE2000 <= {TOL}.\n")
    lines.append(f"Starting error before any correction: median mean-dE2000 = {np.median(start_de):.2f}, "
                 f"10th-90th percentile {np.percentile(start_de, 10):.2f} to {np.percentile(start_de, 90):.2f}.\n")
    lines.append(f"Headline settings: measurement noise {SIGMA} Lab units, engineer's mental-model error "
                 f"{int(HUMAN_ERR*100)}%, advisor starting-model error {int(PRIOR_ERR*100)}%.\n")
    lines.append("CAUTION: neither manual loop below is calibrated to real QC engineers. 'Crude' only changes "
                 "one channel at a time; 'Expert by eye' does combined changes but never learns from the lab. "
                 "Treat them as a bracket, not a baseline. The real baseline comes from the client's lab logs.\n")
    lines.append("| Measure | Manual (crude) | Manual (expert by eye) | Advisor |\n|---|---|---|---|")
    for label, key, fmt in [
        ("Median rounds to accept", "median_rounds", "{:.0f}"),
        ("Accepted within 1 round", "within_1_round_pct", "{:.0f}%"),
        ("Accepted within 2 rounds", "within_2_rounds_pct", "{:.0f}%"),
        (f"Not accepted after {MAX_ROUNDS} rounds", "not_accepted_pct", "{:.0f}%"),
        ("Median variants printed", "median_variants", "{:.0f}"),
        ("Median TRUE dE2000 at the end", "median_true_dE_final", "{:.2f}"),
        (f"False accepts (true dE2000 > {TOL+0.5})", "false_accept_pct", "{:.0f}%"),
    ]:
        lines.append(f"| {label} | {fmt.format(sm[key])} | {fmt.format(se[key])} | {fmt.format(sa[key])} |")
    lines.append(f"\nShare of events where NO change to the file can reach dE2000 <= {TOL} "
                 f"(best achievable is above tolerance): {share_unfixable:.0f}%. "
                 "These are mostly kiln-type shifts. A real tool must say so instead of iterating.\n")
    lines.append(f"Same comparison restricted to the {int(fixable.sum())} events where the file CAN fix it "
                 "(best achievable dE2000 <= 0.7):\n")
    lines.append("| Measure (fixable events only) | Manual (crude) | Manual (expert by eye) | Advisor |\n|---|---|---|---|")
    for label, key, fmt in [
        ("Median rounds to accept", "median_rounds", "{:.0f}"),
        ("Accepted within 1 round", "within_1_round_pct", "{:.0f}%"),
        ("Accepted within 2 rounds", "within_2_rounds_pct", "{:.0f}%"),
        (f"Not accepted after {MAX_ROUNDS} rounds", "not_accepted_pct", "{:.0f}%"),
    ]:
        lines.append(f"| {label} | {fmt.format(sm_fix[key])} | {fmt.format(se_fix[key])} | {fmt.format(sa_fix[key])} |")
    lines.append("\n## Sensitivity (advisor, share accepted within 2 rounds / not accepted at all)\n")
    lines.append("| Noise (Lab sd) \\ starting-model error | 15% | 25% | 50% | 100% |\n|---|---|---|---|---|")
    for sigma in (0.05, 0.15, 0.30, 0.60):
        cells = []
        for prior in (0.15, 0.25, 0.5, 1.0):
            row = [s for s in sens if s["noise_sd_lab"] == sigma and s["model_error"] == prior][0]
            cells.append(f"{row['advisor_within_2_rounds_pct']:.0f}% / {row['advisor_not_accepted_pct']:.0f}%")
        lines.append(f"| {sigma} | " + " | ".join(cells) + " |")
    lines.append("\n## Sensitivity (manual loop, same noise levels)\n")
    lines.append("| Noise (Lab sd) | Within 2 rounds | Not accepted | Median rounds |\n|---|---|---|---|")
    for sigma in (0.05, 0.15, 0.30, 0.60):
        row = [s for s in sens if s["noise_sd_lab"] == sigma][0]
        lines.append(f"| {sigma} | {row['manual_within_2_rounds_pct']:.0f}% | "
                     f"{row['manual_not_accepted_pct']:.0f}% | {row['manual_median_rounds']:.0f} |")
    with open(os.path.join(a.outdir, "summary.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    make_plot(head, sens, a.outdir)


def make_plot(head, sens, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colours = {"manual": "#7a7a7a", "expert": "#D55E00", "advisor": "#0072B2"}
    names = {"manual": "Manual (crude)", "expert": "Manual (expert by eye)", "advisor": "Advisor"}
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))

    ks = list(range(0, MAX_ROUNDS + 1))
    for key in ("manual", "expert", "advisor"):
        rows = head[key]
        r = np.array([x[0] for x in rows])
        ok = np.array([x[2] for x in rows])
        share = [100 * float(np.mean(ok & (r <= k))) for k in ks]
        ax1.plot(ks, share, color=colours[key], lw=2, marker="o", ms=5)
        nudge = {"expert": 5, "advisor": -5}.get(key, 0)   # keep the two close lines' labels apart
        ax1.text(ks[-1] + 0.15, share[-1] + nudge, names[key], color="#222", va="center", fontsize=9)
    ax1.set_xlim(0, MAX_ROUNDS + 3.2)
    ax1.set_ylim(0, 100)
    ax1.set_xlabel("Physical print-fire-measure rounds used")
    ax1.set_ylabel("% of changeovers accepted (dE2000 <= 1.0)")
    ax1.set_title("How quickly each loop reaches tolerance (synthetic)", fontsize=10, loc="left")

    sigmas = sorted({s["noise_sd_lab"] for s in sens})
    for prior, style, lab in ((0.25, "-", "Starting-model error 25%"), (1.0, "--", "Starting-model error 100%")):
        ys = [[s for s in sens if s["noise_sd_lab"] == sg and s["model_error"] == prior][0]
              ["advisor_within_2_rounds_pct"] for sg in sigmas]
        ax2.plot(sigmas, ys, color=colours["advisor"], lw=2, ls=style, marker="o", ms=5)
        col = colours["advisor"]
        ax2.text(sigmas[-1] + 0.02, ys[-1], lab, color="#222", va="center", fontsize=9)
    ax2.set_xlim(0, sigmas[-1] + 0.55)
    ax2.set_ylim(0, 100)
    ax2.set_xlabel("Measurement noise (Lab units, 1 std dev)")
    ax2.set_ylabel("% accepted within 2 rounds")
    ax2.set_title("Advisor: what breaks it (synthetic)", fontsize=10, loc="left")

    for ax in (ax1, ax2):
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", color="#dddddd", lw=0.8)
        ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, "convergence.png"), dpi=150)


if __name__ == "__main__":
    main()
