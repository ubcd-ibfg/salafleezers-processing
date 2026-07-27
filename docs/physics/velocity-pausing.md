# Velocity & pausing

Implemented in `salafleezers.analysis.velocity`. Two independent ways to turn an extension
trace into a velocity, plus a way to summarize velocities as a distribution.

## Step-based velocity (`step_velocities`)

Given a KV step-finding result (see [Step-finding theory](step-finding.md)), the velocity of
segment \(i\) is just the level change divided by the dwell time between step boundaries:

\[
v_i = \frac{\text{level}_{i+1} - \text{level}_i}{t_{i+1} - t_i}
\]

Segments where \(|v_i|\) falls below `pause_threshold` (nm/s) are flagged as pauses rather than
motion — useful for e.g. distinguishing a translocating motor's active segments from stalls, and
computing what fraction of total time was spent paused (`pause_fraction`, time-weighted, not
just a count of paused segments). This method is exact wherever step-finding is reliable, but
inherits step-finding's own limitations (see [Step-finding theory](step-finding.md)) and gives
one velocity value per segment rather than a continuous instantaneous velocity.

## Continuous velocity (`savgol_velocity`)

For a continuous instantaneous velocity estimate without needing step-finding first, a
Savitzky-Golay filter fits a local polynomial (`polyorder`, default 2) over a sliding window
(`window` samples, default 21) and differentiates the fitted polynomial analytically at each
point — `scipy.signal.savgol_filter(..., deriv=1)`. This gives one velocity value per *sample*,
smoothed enough to be usable despite the derivative amplifying high-frequency noise (a moving
average without fitting a polynomial first would systematically bias the derivative near any
curvature in the signal; the local-polynomial fit avoids that).

The tradeoff versus step-based velocity: no dependence on step-finding parameters, but no
principled way to separate "moving" from "paused" — the CLI/GUI's `sfz velocity` command
reports a full histogram (below) rather than a pause fraction, since a fixed threshold on a
noisy continuous derivative is much less reliable than thresholding averaged step-segment
velocities.

## Velocity distributions (`velocity_histogram`)

A plain histogram of the velocity values (from either method above) — this is what the GUI's
Velocity analysis panel and `sfz velocity` plot. The underlying function
(`velocity_histogram`) also supports an optional 2-D histogram binned by a matching force
array, for seeing how velocity depends on applied load — that capability exists in the library
today but isn't yet wired into the CLI or GUI (both currently call it velocity-only); see
[Adding an analysis module](../developer/adding-analysis-module.md) if you want to expose it.
