# Optical trapping basics

## The harmonic trap approximation

A dielectric bead held near the focus of a tightly-focused laser beam experiences a restoring
force toward the beam's intensity maximum. For small displacements \(x\) from the trap centre,
this force is linear:

\[
F = -\kappa x
\]

where \(\kappa\) (pN/nm) is the **trap stiffness**. This is the same physics as a bead on a
spring, and it's the reason the whole calibration pipeline below is just "measure a spring
constant" — but measured through Brownian motion rather than a static deflection test, since
you can't easily apply a known force to a bead at this scale.

## QPD position detection

The bead's position within the trap is read out with a quadrant photodiode (QPD): the
interference pattern of the trapping laser scattered off the bead produces a voltage signal
proportional to bead displacement, for small displacements. `salafleezers.io.reader` reads
these raw QPD voltages (channels named `AX`, `AY`, `BX`, `BY`, … for trap A/B, X/Y axis — see
[`constants.CHANNEL_MAPS`](../developer/api-reference.md) for the full channel layout) directly
off the digitizer as `int16` — see [Data formats](../user-guide/data-formats.md).

Converting a raw voltage to a displacement in nm requires knowing the **position sensitivity**
\(\alpha\) (nm/V) — one of the two numbers calibration solves for (the other being \(\kappa\)
itself). See [Calibration & trap stiffness](calibration.md).

## Brownian motion in a trap: the power-spectrum method

A trapped bead undergoes Brownian motion, damped by the harmonic trap. Its equation of motion
(overdamped — inertia is negligible at this scale and Reynolds number) is a
Ornstein-Uhlenbeck process:

\[
\gamma \dot{x}(t) = -\kappa x(t) + \xi(t)
\]

where \(\gamma\) is the Stokes drag coefficient and \(\xi(t)\) is thermal (white) noise. The
power spectral density of \(x(t)\) has a closed form — a Lorentzian:

\[
S_x(f) = \frac{D}{2\pi^2 \left(f_c^2 + f^2\right)}
\]

with two parameters that fully describe the trap:

- **Corner frequency** \(f_c = \kappa / (2\pi\gamma)\) — where the spectrum rolls off from flat
  (low frequency, dominated by the trap) to \(1/f^2\) (high frequency, dominated by free
  diffusion).
- **Diffusion coefficient** \(D\), related to \(\gamma\) by the Einstein relation
  \(D = k_BT/\gamma\).

This is the classic Gittes & Schmidt (2002) power-spectrum calibration method — measure the QPD
voltage's power spectrum, fit it to a Lorentzian, and get \(\kappa\) and \(\alpha\) without ever
needing to apply a known force. See [Calibration & trap stiffness](calibration.md) for exactly
how `salafleezers.calibration` implements this fit, including the aliasing correction needed
because real digitizers sample at a finite rate.

## Why timeshared, dual-trap

SalaFleezer holds **two** optical traps (A and B) by rapidly time-sharing one laser beam
between two positions (steered by an acousto-optic/DDS deflector — see
`constants.CONV_TRAP_X_NM_PER_MHZ`, the calibration converting DDS drive frequency to physical
trap separation in nm). A single molecule (DNA, a folded protein, a translocating motor) is
tethered between a bead in trap A and a bead in trap B. This dual-trap geometry is what lets
the instrument measure **force and extension directly across the tethered molecule**, rather
than against a fixed pipette or surface — eliminating drift and surface-attachment artifacts
common to single-trap assays. See [Force & extension](force-extension.md) for how force and
extension are actually computed from the two traps' calibrated signals.
