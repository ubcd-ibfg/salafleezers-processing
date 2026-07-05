# Calibration & trap stiffness

Implemented in `salafleezers.calibration` (`power_spectrum.py`, `lorentzian.py`, `fit.py`),
ported from `tscalibrate.m` / `Lorentzian.m` / `tscalibrate_lorentzguess.m`.

## Pipeline

`calibration.fit.calibrate()` runs five steps on one detector channel's normalized voltage
signal (see [Force & extension](force-extension.md) for what "normalized" means):

1. **Power spectrum** (`power_spectrum.compute_power_spectrum`) — one-sided FFT power spectral
   density of the raw signal.
2. **Bin** (`bin_spectrum`) — average the PSD into `n_bin` uniform-width bins (default 1563
   points/bin) to reduce fit noise; a raw single-sided PSD is extremely noisy point-to-point
   (each frequency bin is a single \(\chi^2_2\)-distributed sample).
3. **Initial guess** (`lorentz_guess`) — a closed-form linear estimator. Since
   \(S(f) = D/(2\pi^2)/(f_c^2+f^2)\) implies \(1/S(f) = (2\pi^2/D)(f_c^2 + f^2)\), which is
   *linear* in \(f^2\), a single `lstsq` line fit through \((f^2,\,1/S)\) gives closed-form
   \(f_c\) and \(D\) starting guesses — no iteration needed, and it can't fail to converge.
4. **Nonlinear fit** (`fit_lorentzian`) — refines \((f_c, D)\) via
   `scipy.optimize.least_squares` in log-space (mirrors MATLAB's `lsqnonlin` on log-residuals,
   which weights the fit evenly across the whole log-log spectrum rather than being dominated
   by the largest-magnitude low-frequency points).
5. **Physical conversion** — turns the fit's \((f_c, D_{\text{fit}})\) (in raw detector-voltage
   units) into \(\alpha\) (nm/V) and \(\kappa\) (pN/nm).

## The aliasing correction

Real digitizers sample at a finite rate \(F_s\), so the theoretical Lorentzian above isn't
quite what you measure — spectral power above the Nyquist frequency folds back
(aliases) into the measured band. `lorentzian.lorentzian_pure` sums the Lorentzian over
aliasing replicas:

\[
S(f) = \sum_{n=-n_{\text{alias}}}^{n_{\text{alias}}} \frac{D}{2\pi^2\left(f_c^2 + (f + nF_s)^2\right)}
\]

with `n_alias=20` by default — enough that additional terms are negligible for typical
SalaFleezer sampling rates (tens of kHz).

## From fit parameters to physical units

Given the fitted \((f_c, D_{\text{fit}})\), a bead radius \(r_a\), water viscosity \(\eta\), and
thermal energy \(k_BT\):

**Stokes drag:**
\[
\gamma = 6\pi\eta r_a
\]

**Theoretical diffusion coefficient** (Einstein relation), in physical units (nm²/s):
\[
D_{\text{theory}} = \frac{k_BT}{\gamma}
\]

**Position sensitivity** — since the *fitted* \(D_{\text{fit}}\) is in raw detector-voltage
units (V²/s) but represents the same physical diffusion process, the ratio of the two gives the
nm-per-volt conversion:
\[
\alpha = \sqrt{\frac{D_{\text{theory}}}{D_{\text{fit}}}} \quad \text{(nm/V)}
\]

**Trap stiffness** — from the corner-frequency relation \(f_c = \kappa/(2\pi\gamma)\):
\[
\kappa = 2\pi\gamma f_c \quad \text{(pN/nm)}
\]

Default physical constants (`constants.py`, all overridable via CLI options or
`ProcessingOptions`):

| Constant | Value | Meaning |
| --- | --- | --- |
| `KT_24C` | 4.10 pN·nm | \(k_BT\) at 24°C |
| `WATER_VISC_24C` | 9.1×10⁻¹⁰ pN·s/nm² | Water viscosity at 24°C |
| `BEAD_RADIUS_NM` | 500 nm | Default bead radius \(r_a\) |

Each trap/axis (`AX`, `BX`, `AY`, `BY`) is calibrated independently — `sfz calibrate` reports
\(f_c\), \(\alpha\), and \(\kappa\) for all four. A hydrodynamic-correction variant
(`lorentzian.lorentzian_hydro`, accounting for frequency-dependent drag near a surface) is
implemented but not used by default — see its docstring for when it matters.
