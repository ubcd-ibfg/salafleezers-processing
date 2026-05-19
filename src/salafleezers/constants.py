"""Instrument constants for the SalaFleezer optical tweezers."""

from __future__ import annotations

# --- Voltage conversion ---
# FPGA reads voltages in [-10, 10] V as int16; 2^15 - 1 = 32767 maps to 10 V
INT16_TO_VOLT: float = 1.0 / 3276.7

# --- Trap position ---
# DDS frequency → nm of trap separation along X
# From loadfile_wrapper.m (SalaFleezer case): convTrapX = 133.1416 nm/MHz
CONV_TRAP_X_NM_PER_MHZ: float = 133.1416

# DDS frequency conversion: raw uint64 → MHz
# posdat (uint48 stored as uint64) * 49.152 * 6 / 2^48
POS_TO_MHZ: float = 49.152 * 6 / 2**48

# --- Physical constants (defaults, can be overridden per experiment) ---
KT_24C: float = 4.10       # kB·T at 24 °C, pN·nm
WATER_VISC_24C: float = 9.1e-10  # water viscosity at 24 °C, pN·s/nm²
BEAD_RADIUS_NM: float = 500.0    # default bead radius, nm

# --- Calibration defaults ---
CAL_FMIN_HZ: float = 100.0   # lower fit frequency, Hz
CAL_NBIN: int = 1563          # points per spectral bin
CAL_N_ALIAS: int = 20         # aliasing window half-width

# --- Channel ID → channel name/index/polarity maps ---
# Each entry: list of (name, data_index_0based, polarity)
# Matches the switch(chnid) in timeshareread.m exactly.
# data_index is 0-based (MATLAB was 1-based).
CHANNEL_MAPS: dict[int, list[tuple[str, int, int]]] = {
    0: [  # 9 chns, one trap with feedback XS
        ("AY",  0, +1), ("AX",  1, +1), ("AS",  3, +1),
        ("AFbS", 2, +1),
        ("BY",  4, +1), ("BX",  5, +1), ("BYS", 6, +1), ("BXS", 7, +1),
        ("BS",  6, +1),
    ],
    1: [  # 12 data chns
        ("AY", 0, +1), ("AX",  1, +1), ("AS",  2, +1),
        ("BY", 3, +1), ("BX",  4, +1), ("BS",  5, +1),
        ("AFbS", 6, +1), ("BFbS", 7, +1),
        ("CY", 8, +1), ("CX",  9, +1), ("CS", 10, +1), ("CSX", 11, +1),
    ],
    2: [  # 13 data chns — SalaFleezer default ("Two traps + QPD + FB. Flzr default.")
        ("AY",   0, +1), ("AX",   1, +1), ("AS",   2, +1),
        ("BY",   3, +1), ("BX",   4, +1), ("BS",   5, +1),
        ("AFbX", 6, -1), ("AFbS", 7, -1),
        ("BFbX", 8, -1), ("BFbS", 9, -1),
        ("CY",  10, +1), ("CX",  11, +1), ("CS",  12, +1), ("CSX", 12, -1),
    ],
    3: [  # 8 chns, one trap; set A = B
        ("AY",  0, +1), ("AX",  1, +1), ("AS",  3, +1),
        ("BY",  0, +1), ("BX",  1, +1), ("BS",  3, +1),
        ("AFbX", 7, -1), ("AFbS", 2, +1),
        ("CY",  4, +1), ("CX",  5, +1), ("CS",  6, +1), ("CXS", 6, -1),
    ],
    4: [  # 14 chns, two traps with fb XYS
        ("AY",   0, +1), ("AX",   1, +1), ("AS",   2, +1),
        ("BY",   3, +1), ("BX",   4, +1), ("BS",   5, +1),
        ("AFbY", 6, -1), ("AFbX", 7, -1), ("AFbS", 8, +1),
        ("CY",   9, -1), ("CX",  10, -1), ("CYS", 11, +1),
        ("CXS", 12, +1), ("_14", 13, +1), ("_15", 13, -1),
    ],
    7: [  # 14 chns + EMCCD (Avogadro)
        ("AY",   0, +1), ("AX",   1, +1), ("AS",   2, +1),
        ("BY",   3, +1), ("BX",   4, +1), ("BS",   5, +1),
        ("AFbX", 6, -1), ("AFbS", 7, -1),
        ("BFbX", 8, -1), ("BFbS", 9, -1),
        ("CY",  10, +1), ("CX",  11, +1), ("CS",  12, +1), ("CSX", 12, -1),
        ("EMCCD", 13, +1),
    ],
}

# File name format: YYMMDD_NNN.dat  (e.g. 230415_001.dat)
DAT_FILENAME_FORMAT: str = "{mmddyy}_{num:03d}.dat"
