% Generate a golden fixture for AFindStepsV5.m (Kalafut-Visscher step-finding).
%
% Requires C_qe compiled for the current platform:
%   cd legacy/BLabOTMatlab/DataGUIs/StepFind_KV
%   CC=/usr/bin/gcc CXX=/usr/bin/g++ mkoctfile --mex C_qe.c
% (the compiled C_qe.mex is a local build artifact, not committed -- see
%  tests/golden/generate/README.md)
%
% Note: MATLAB's inPenalty parameterization (relative fractional QE decrease,
% P = exp(-inPenalty/len)-1) is NOT the same formula as Python's
% analysis.stepfind.kv.find_steps pen_factor (absolute chi2 threshold =
% pen_factor * var(data) * ln(N)). They are different penalty scales for the
% same underlying algorithm, so this fixture is used to check that both
% recover the *same step positions and levels* on an unambiguous synthetic
% staircase, not that pen_factor=2.0 numerically equals inPenalty=single(2).
%
% Run with: octave-cli --no-gui gen_kv.m

here = fileparts(mfilename('fullpath'));
repo_root = fullfile(here, '..', '..', '..');
addpath(fullfile(repo_root, 'legacy', 'BLabOTMatlab', 'DataGUIs', 'StepFind_KV'));

% 5-step staircase with Gaussian noise, high SNR so both algorithms recover
% the exact same steps regardless of moderate penalty-scale differences.
% The noise is generated once here with a fixed RNG seed and then frozen
% into the saved .mat/.npz fixture, so later test runs never re-invoke any
% RNG (MATLAB/Octave/numpy) -- they just load this exact array.
n = 5000;
contour = zeros(1, n);
step_starts = [1000 2000 3000 4000];
step_heights = [8 8 8 8];
for i = 1:length(step_starts)
    contour(step_starts(i)+1:end) = contour(step_starts(i)+1:end) + step_heights(i);
end
rand('seed', 42);
randn('seed', 42);
contour = contour + 0.5 * randn(1, n);

[outInd, outMean, outTra] = AFindStepsV5(contour, single(2));

out_dir = fullfile(here, '..', 'fixtures', 'raw');
mkdir(out_dir);
save('-v6', fullfile(out_dir, 'kv.mat'), 'contour', 'outInd', 'outMean', 'outTra');
printf('wrote %s (%d steps found)\n', fullfile(out_dir, 'kv.mat'), length(outMean)-1);
