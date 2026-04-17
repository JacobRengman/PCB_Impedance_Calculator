# PCB Impedance Calculator

A Windows desktop tool for calculating the characteristic impedance of common PCB transmission line structures. It generates cross-section images of the stackup and feeds them into the [ATLC2](http://www.hdtvprimer.com/kq6qv/atlc2.html) 2D field solver to produce accurate impedance, attenuation, and velocity factor results.

![License: GPL v2](https://img.shields.io/badge/License-GPL%20v2-blue.svg)

---

## Features

- Live cross-section preview that updates as you type
- Five supported transmission line structures:
  - **Microstrip** — single trace above a ground plane
  - **Stripline** — trace embedded between two ground planes
  - **CPWG** — Coplanar Waveguide with Ground (4-layer stackup)
  - **Differential pair** — two coupled surface traces
  - **Embedded differential pair** — two coupled buried traces
- Analytical IPC-2141 impedance prediction shown before simulation
- Full differential simulation (even + odd mode) for differential pairs
- Configurable FR4 and solder mask dielectric constants
- Optional cleanup of intermediate files after simulation
- Automatic download of ATLC2 if not found

---

## Requirements

### Operating System
**Windows only.** The simulation backend (ATLC2) is a Windows executable. The image generation and IPC-2141 prediction work on any platform, but the simulation button requires Windows.

### Python
Python 3.8 or newer.

### Python packages
```
pip install numpy Pillow
```

### ATLC2
The field solver `atlc2.exe` must be placed in the same directory as the script, or downloaded automatically via the dialog that appears on first launch.

- Homepage: http://www.hdtvprimer.com/kq6qv/atlc2.html
- Direct download (Win64): http://www.hdtvprimer.com/KQ6QV/Win64/atlc2.exe

---

## Installation

```bash
git clone https://github.com/yourusername/pcb-impedance-calculator.git
cd pcb-impedance-calculator
pip install numpy Pillow
python PCB_Impedance_Calculator.py
```

On first launch, if `atlc2.exe` is not found in the current directory, a dialog will offer to download it automatically or let you skip and use the tool for image generation and predictions only.

---

## Usage

1. Select the transmission line type from the tabs at the top
2. Enter your PCB stackup dimensions (in micrometres)
3. The cross-section preview and IPC-2141 prediction update automatically
4. Set a filename and click **Run ATLC2 Simulation**
5. Results appear on the right when the simulation completes

### General settings

| Field | Description |
|---|---|
| Image Scale (um/pixel) | Controls the resolution of the generated PNG. Smaller = higher resolution but slower simulation. 5 um/px is a good starting point. |
| Total Image Width (um) | Width of the simulation canvas. Should be wide enough that the fields decay to zero at the edges. |
| Total Image Height (um) | Height for microstrip-type structures. Stripline height is calculated automatically from the stackup. |
| Frequency (MHz) | Used to compute attenuation and complex impedance from the RLGC parameters. |
| FR4 Er | Relative permittivity of the FR4 dielectric. Typical values: 4.0–4.8. |
| Solder Mask Er | Relative permittivity of the solder mask. Typical value: 3.5–4.5. |

### Differential pair simulation modes

| Checkbox | Behaviour |
|---|---|
| Full Diff Sim (Odd + Even) | Runs two sequential simulations. Gives Zdiff, Zcomm, Zodd, Zeven, and the geometric-mean Z0. |
| *(unchecked)* | Runs a single odd-mode simulation. Gives Zdiff and Zodd only. Faster. |

### Keep Intermediate Results

When unchecked (default), all generated files are deleted after the result is retrieved:
- The cross-section PNG(s)
- `StartupScript.txt`
- `MoreColors.txt`
- All ATLC2 result `.txt` files

Check this box if you want to inspect the generated images or result files, or if you intend to re-run ATLC2 manually.

---

## How it works

### Image generation

The script converts the stackup dimensions into a pixel-accurate RGB cross-section image. Each material is represented by a specific colour:

| Colour | Material | RGB |
|---|---|---|
| Black | Vacuum / air | (0, 0, 0) |
| Red | Signal trace (+1 V) | (255, 0, 0) |
| Blue | Signal trace (−1 V, even mode) | (0, 0, 255) |
| Green | Ground copper | (0, 255, 0) |
| Yellow-green | FR4 dielectric | (223, 247, 136) |
| Brown | Solder mask | (188, 127, 96) |

A 2-pixel wide green bar is painted on the left and right edges of every image to stitch all ground layers together into a single connected net. This is required because ATLC2 needs ground to form one continuous region to produce correct results.

### ATLC2 integration

The script writes a `MoreColors.txt` file that tells ATLC2 the dielectric constants for FR4 and solder mask (identified by their pixel colours). It then writes a `StartupScript.txt` and launches `atlc2.exe`, which performs a 2D finite-element solve and writes per-unit-length RLGC parameters to text files. The Python script polls these files once per second and, once they are populated, computes:

- **Z0** from the telegrapher's equation: Z0 = √((R + jωL) / (G + jωC))
- **Alpha** (attenuation): real part of the propagation constant γ = √((R + jωL)(G + jωC)), converted from Np/m to dB/cm
- **Velocity factor** from the VFactors file written by ATLC2, or estimated as 1 / (c√(LC)) if that file is absent

### IPC-2141 analytical predictions

While you are entering dimensions, the tool shows an instant impedance estimate using closed-form IPC-2141 approximations. These ignore solder mask and coplanar ground effects and are less accurate than the field solver, but are useful for getting in the right ballpark before running a simulation.

For CPWG structures the Hilberg approximation for the complete elliptic integral ratio K(k)/K(k') is used instead of the IPC formula, which does not cover coplanar geometries.

---

## Project structure

```
PCB_Impedance_Calculator.py   — entire application (single file)
README.md                     — this file
```

The application is intentionally kept as a single Python file to make it easy to share and run without any package installation beyond numpy and Pillow.

---

## Contributing

Contributions are welcome. Some areas that would benefit from work:

- Support for additional transmission line structures (e.g. edge-coupled stripline, broadside-coupled)
- Input validation improvements
- A way to save and reload configurations
- Linux/macOS support if a cross-platform field solver becomes available
- Unit tests for the physics calculation functions

Please open an issue before starting significant work so we can discuss the approach.

---

## Known limitations

- **Windows only** — ATLC2 is a Windows executable. See above.
- **Single-file architecture** — makes the codebase harder to test and extend as it grows. A future refactor into separate modules is planned.
- **ATLC2 polling** — the script detects simulation completion by watching for output files rather than listening to the process. This means a one-second delay between completion and result display.
- **GND stitching** — a 2-pixel wide green bar on the image edges is used to connect ground layers. This is a workaround for an ATLC2 requirement and slightly affects the field distribution at the very edge of the image, but has negligible effect on results when the image is wide enough.

---

## License

Copyright (C) 2026 Jacob Rengman, IRR AB, jacob.rengman@irr.se

This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation; either version 2 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program; if not, write to the Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
