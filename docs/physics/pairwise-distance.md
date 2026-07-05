# Pairwise-distance (PWD) method

Implemented in `salafleezers.analysis.pwd`, port of `calcPWDV1b.m` / `sumPWD*.m` /
`findPWDpeaks.m` / `acorr2.m`.

## The idea

If a trace is made of discrete steps of size \(d\) (even if you don't know exactly where the
steps are, or the trace is too noisy for reliable step-finding), then the distribution of
*pairwise differences* between all pairs of data points \(x_i - x_j\) has peaks at
\(\delta = 0, \pm d, \pm 2d, \dots\) — every pair of points sitting on the same level
contributes to the peak at 0; every pair one step apart contributes to the peak at \(\pm d\);
and so on. This makes PWD a useful complement to step-finding: it can recover a characteristic
step size directly from the data's *statistics*, without ever explicitly locating where each
step occurs, so it degrades more gracefully in high noise or with imperfect step localization.

## Computing it efficiently: autocorrelation via FFT

The naive pairwise-difference histogram is \(O(N^2)\) — every pair of points. But the PWD
histogram is exactly the **autocorrelation of the data's own histogram**:

\[
\text{PWD}(\delta) = \sum_{i,j} \delta(x_i - x_j - \delta) = (h \star \tilde h)(\delta)
\]

where \(h\) is the histogram of \(x\) values and \(\tilde h(x)=h(-x)\) is its reflection. An
autocorrelation is a convolution with a reflected copy of itself, which the FFT computes in
\(O(M\log M)\) (\(M\) = number of histogram bins) — the Wiener-Khinchin theorem, the same trick
`analysis.stats.msd_fft` uses to make mean-squared-displacement tractable for long traces. So
the total cost here is \(O(N)\) to build the histogram plus \(O(M\log M)\) for the FFT
autocorrelation, independent of how large \(N\) (trace length) is — only the number of bins
\(M\) matters for the expensive part.

## Peak detection

Once the PWD histogram is computed, `scipy.signal.find_peaks` locates local maxima (excluding
the trivial \(\delta=0\) peak), keeping only peaks with prominence above 1% of the maximum PWD
count — a simple noise floor to avoid reporting spurious single-bin fluctuations as step sizes.
Each detected peak's position gives a candidate step size (nm), and its height/prominence gives
a rough measure of how well-represented that step size is in the data.

## Using it

`sfz pwd` / the GUI's Pairwise distance panel take one channel (typically extension) and a bin
count, and report both the full PWD histogram (for visual inspection — genuine step sizes show
up as clean, evenly-spaced peaks; noise or continuous motion shows up as a smooth decay with no
sharp peaks) and the list of detected peak positions/heights. It's often run *before*
step-finding to get a good `pen_factor`/expected-step-size prior, and *after* to cross-check
that the KV/HMM result's step sizes match what PWD independently finds in the raw data.
