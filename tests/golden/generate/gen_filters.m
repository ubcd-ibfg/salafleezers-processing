% Generate a golden fixture for windowFilter.m (mean filter, centred window).
%
% Run with: octave-cli --no-gui gen_filters.m
% Requires: legacy/BLabOTMatlab vendored as a submodule (DataGUIs/StepFind_KV/windowFilter.m).
%
% Output: tests/golden/fixtures/raw/filters.mat  (loaded + converted to .npz by convert_mat_to_npz.py)

here = fileparts(mfilename('fullpath'));
repo_root = fullfile(here, '..', '..', '..');
addpath(fullfile(repo_root, 'legacy', 'BLabOTMatlab', 'DataGUIs', 'StepFind_KV'));

% Deterministic synthetic signal: no RNG, so the fixture is exactly
% reproducible without depending on MATLAB/Octave's RNG implementation.
n = 2000;
t = (0:n-1) / n;
x = sin(2*pi*3*t) + 0.3*sin(2*pi*17*t + 1) + 0.1*sin(2*pi*97*t);

hw5 = windowFilter(@mean, x, 5, 1);
hw20 = windowFilter(@mean, x, 20, 1);

out_dir = fullfile(here, '..', 'fixtures', 'raw');
mkdir(out_dir);
save('-v6', fullfile(out_dir, 'filters.mat'), 'x', 'hw5', 'hw20');
printf('wrote %s\n', fullfile(out_dir, 'filters.mat'));
