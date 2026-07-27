# Force & extension

Implemented in `salafleezers.processing.pipeline.process_one` and `salafleezers.analysis.wlc`.

## From calibrated voltage to force and extension

Each trap axis's calibration (see [Calibration & trap stiffness](calibration.md)) gives a
position sensitivity \(\alpha\) (nm/V) and stiffness \(\kappa\) (pN/nm). Per-axis force is
simply the harmonic-trap relation \(F=\kappa x\), i.e. \(F = \alpha\kappa \cdot V\) directly on
the calibrated voltage signal \(V\).

**Differential force** across the tether — the two beads pull on each other, so trap A and trap
B report roughly opposite forces; averaging the *difference* halves the readout noise that's
common to both:

\[
F = \sqrt{\left(\frac{F_{BX}-F_{AX}}{2}\right)^2 + \left(\frac{F_{BY}-F_{AY}}{2}\right)^2}
\]

**Extension** — the bead-to-bead distance, which is the trap-to-trap separation (the DDS-driven
trap A/B offset, \(T_X\), converted to nm — see `constants.CONV_TRAP_X_NM_PER_MHZ`) corrected by
each bead's *measured* displacement within its own trap, minus both bead radii and any
user-supplied offset:

\[
\text{ext} = \sqrt{\left(T_X + \alpha_{AX}V_{AX} - \alpha_{BX}V_{BX}\right)^2 +
                    \left(T_Y + \alpha_{AY}V_{AY} - \alpha_{BY}V_{BY}\right)^2}
             - r_A - r_B - \text{ext\_offset}
\]

(\(T_Y=0\) always for this timeshared instrument — see
[Optical trapping basics](optical-trapping.md).) Subtracting the bead radii converts
centre-to-centre distance to the actual tether's end-to-end length.

## The worm-like chain (WLC) model

A polymer tether (dsDNA, an unfolded protein, RNA) under tension doesn't stretch like a Hookean
spring — its extension vs. force curve is the entropic worm-like chain (WLC), governed by two
parameters: **persistence length** \(P\) (how "stiff"/how quickly the polymer's direction
decorrelates, nm) and **contour length** \(L_c\) (its fully-stretched length, nm), plus an
optional stretch modulus \(S\) (pN) for the *extensible* correction that matters at higher
forces (the "eXtensible WLC", XWLC).

`salafleezers.analysis.wlc.xwlc_extension` implements three formulations (all give
\(x/L_c\) as a function of force):

- **`"basic"`** — the classic Odijk (1995) approximation:
  \[
  \frac{x}{L_c} \approx 1 - \frac{1}{2}\sqrt{\frac{k_BT}{PF}} + \frac{F}{S}
  \]
  Golden-tested against an independently computed reference — see
  [Testing & golden files](../developer/testing-golden-files.md).

- **`"marko_siggia"`** — the full Marko-Siggia (1995) interpolation formula, self-consistently
  inverted (numerically, via `scipy.optimize.brentq`) to account for the extensible correction:
  \[
  F(t) = \frac{k_BT}{P}\left[\frac{1}{4(1-t)^2} - \frac{1}{4} + t\right], \quad
  t = \frac{x_{\text{eff}}}{L_c}, \quad x_{\text{eff}} = x - \frac{L_cF}{S}
  \]

- **`"bouchiat"`** — the Bouchiat et al. (1999, *Biophys J* 76:409) polynomial correction to
  Marko-Siggia, adding seven correction terms \(a_2 t^2 + \dots + a_7 t^7\) to the force
  equation above for a substantially more accurate fit near \(t\to1\) (full extension).

!!! note "Why only `basic` is golden-tested"
    `"marko_siggia"` and `"bouchiat"` are standard alternative formulations from the literature
    cited above, not variants of the `"basic"` method's exact algebra, so there's no shared
    reference output to validate them against the same way. Only `"basic"` has an independently
    computed golden fixture.

## Fitting

`salafleezers.analysis.wlc.fit_force_ext` fits \(P\), \(L_c\),
optionally \(S\), and optionally \(x\)/\(F\) offsets to an experimental \((F, x)\) curve via
`scipy.optimize.least_squares`, minimizing the residual between measured extension and the
model's predicted extension at each measured force. Both the CLI (`sfz wlc-fit`) and the GUI's
Force-Extension viewer call this same function — see
[Architecture](../developer/architecture.md).
