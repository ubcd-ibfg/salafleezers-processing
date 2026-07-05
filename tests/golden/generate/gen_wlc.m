% Generate a golden fixture for XWLC.m (method 1, "Basic theory").
%
% Note: Python's wlc.xwlc_extension only ports MATLAB method 1 ("basic")
% literally. Methods 2 ("legacy"/phage) and 3 ("wikipedia") were replaced in
% the Python port by the more standard Marko-Siggia and Bouchiat formulations
% instead of being ported verbatim -- see COMPARISON.md. So only method 1 is
% golden-tested here.
%
% Run with: octave-cli --no-gui gen_wlc.m

here = fileparts(mfilename('fullpath'));
repo_root = fullfile(here, '..', '..', '..');
addpath(fullfile(repo_root, 'legacy', 'BLabOTMatlab', 'DataGUIs', 'ForceExt'));

F = linspace(0.5, 40, 300);
P = 50;
S = 900;
kT = 4.14;

x_over_L = XWLC(F, P, S, kT, 1);

out_dir = fullfile(here, '..', 'fixtures', 'raw');
mkdir(out_dir);
save('-v6', fullfile(out_dir, 'wlc.mat'), 'F', 'P', 'S', 'kT', 'x_over_L');
printf('wrote %s\n', fullfile(out_dir, 'wlc.mat'));
