#!/usr/bin/env python3
# -*- coding: utf-8 -*-
program_name = "PCB Impedance Calculator V1.0.5"
"""
PCB Impedance Calculator - This script allows you to create images of the most common
PCB transmission line structures like microstrips, striplines and more. It can then
start the 2D field solver ATLC2 to simulate the impedance and transmission losses
of the created structures.

The script only runs on Windows since ATLC2 only runs on windows. The field solver
ATLC2 is a third party application and is not written by the author of this script.

Copyright (C) 2026 Jacob Rengman, IRR AB, jacob.rengman@irr.se

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import os
import sys
import subprocess
import threading
import re
import math
import cmath
import time
import ctypes
from ctypes.wintypes import RECT
import urllib.request
import webbrowser

# --- Safely Import 3rd Party Dependencies ---
try:
    import numpy as np
    from PIL import Image, ImageTk
except ImportError as e:
    root = tk.Tk()
    root.withdraw() 
    messagebox.showerror(
        "Missing Dependencies", 
        f"A required library is missing:\n{e}\n\n"
        "Please install the required Python packages by running:\n"
        "pip install numpy Pillow"
    )
    sys.exit(1)

# --- Default Parameters ---
# All dimensional values are in micrometres (um).
# Key naming convention:
#   Prefix  = structure type: cpwg_ / ms_ / sl_ / dp_ / edp_
#   _t_     = thickness of a copper layer
#   _d_ / _h_ = dielectric layer height
#   _w_     = trace width
#   _s_     = gap / spacing
#   _sm_    = solder mask thickness
#   _gnd_   = ground plane copper thickness
# These are loaded into the GUI on startup and can be freely edited here
# to change the default values shown when the application is opened.
DEFAULTS = {
    'scale_um_per_px': 5.0,  
    'img_width_um': 2000.0,
    'img_height_um': 1000.0,
    'sim_frequency_mhz': 1000.0,
    
    'fr4_er': 4.5,
    'solder_mask_er': 4.0,
    
    'cpwg_sm_um': 25.0,
    'cpwg_t_top_um': 35.0,
    'cpwg_d1_um': 200.0,
    'cpwg_t_in1_um': 20.0,
    'cpwg_d2_um': 100.0,
    'cpwg_t_in2_um': 35.0,
    'cpwg_d3_um': 300.0,
    'cpwg_t_bot_um': 35.0,
    'cpwg_w_um': 560.0,
    'cpwg_s_um': 400.0,
    
    'ms_sm_um': 25.0,
    'ms_t_um': 35.0,
    'ms_h_um': 200.0,
    'ms_gnd_um': 35.0,
    'ms_w_um': 350.0,
    'ms_s_gap_um': 600.0,
    
    'sl_t_um': 35.0,
    'sl_h1_um': 200.0,
    'sl_h2_um': 200.0,
    'sl_gnd_um': 35.0,
    'sl_w_um': 130.0,
    'sl_s_gap_um': 600.0,
    
    'dp_sm_um': 25.0,
    'dp_t_um': 35.0,
    'dp_h_um': 200.0,
    'dp_gnd_um': 35.0,
    'dp_w_um': 200.0,
    'dp_s_um': 200.0,
    'dp_s_gap_um': 600.0,
    
    'edp_t_um': 35.0,
    'edp_h1_um': 200.0,
    'edp_h2_um': 200.0,
    'edp_gnd_um': 35.0,
    'edp_w_um': 100.0,
    'edp_s_um': 100.0,
    'edp_s_gap_um': 600.0,

    'filename': 'microstrip.png'
}

# Pixel colours used when generating the cross-section images for ATLC2.
# ATLC2 identifies materials by their exact RGB colour values, so these must
# not be changed without also updating MoreColors.txt (written at sim time).
# Red   (+1V) and Blue (-1V) identify signal conductors; Green = GND copper.
COLORS = {
    'vacuum':       (0,   0,   0),    # Black  — surrounding vacuum / air
    'red_cu_p1v':   (255, 0,   0),    # Red    — signal trace at +1 V
    'blue_cu_m1v':  (0,   0,   255),  # Blue   — signal trace at -1 V (diff pair even mode)
    'green_cu_gnd': (0,   255, 0),    # Green  — ground copper (all GND layers)
    'fr4':          (223, 247, 136),  # Yellow — FR4 dielectric (Er set in MoreColors.txt)
    'solder_mask':  (188, 127, 96),   # Brown  — solder mask (Er set in MoreColors.txt)
}

def draw_rectangle(arr, x_left_px, x_right_px, y_bot_px, y_top_px, color, img_h_px):
    """
    Paint a filled rectangle into a numpy image array.

    The coordinate system used throughout generate_image() has y=0 at the
    BOTTOM of the image (physical bottom of the PCB stackup), increasing
    upward.  NumPy arrays are indexed top-to-bottom, so this function
    converts y coordinates before writing.  All coordinates are in pixels
    and are clamped to the array bounds so out-of-range draws are silently
    clipped rather than raising an exception.

    Args:
        arr          : numpy array of shape (height, width, 3), dtype uint8
        x_left_px    : left edge of the rectangle in pixels (physical coords)
        x_right_px   : right edge of the rectangle in pixels (physical coords)
        y_bot_px     : bottom edge in pixels (y=0 is bottom of image)
        y_top_px     : top edge in pixels (y=0 is bottom of image)
        color        : RGB tuple, e.g. (255, 0, 0)
        img_h_px     : total image height in pixels (needed for y-flip)
    """
    img_w_px = arr.shape[1]
    xl = max(0, int(round(x_left_px)))
    xr = min(img_w_px, int(round(x_right_px)))
    row_top_idx = img_h_px - int(round(y_top_px))
    row_bot_idx = img_h_px - int(round(y_bot_px))
    rt = max(0, row_top_idx)
    rb = min(img_h_px, row_bot_idx)

    if xl >= xr or rt >= rb:
        return 

    arr[rt:rb, xl:xr] = color

def generate_image(params, is_even_mode=False):
    """
    Generate a cross-section bitmap of the selected transmission line structure.

    The image is consumed by ATLC2 as its input.  Each pixel colour maps to a
    material (see COLORS dict).  The stackup is drawn bottom-up: y=0 is the
    physical bottom of the board.  A 2-pixel wide green GND bar is painted on
    the left and right edges to ensure all ground layers are electrically
    connected in the ATLC2 mesh — this is required because ATLC2 needs all
    GND regions to be a single connected net.

    Args:
        params      : dict produced by get_params_from_gui(), containing all
                      dimensional and simulation parameters.
        is_even_mode: when True, both signal traces are drawn red (+1V),
                      modelling even (common) mode excitation for diff pairs.
                      When False (default), trace 2 is blue (-1V) = odd mode.

    Returns:
        PIL.Image.Image: RGB image ready to be saved as a PNG for ATLC2.
    """
    scale = params['scale_um_per_px']
    w_total_um = params['img_width_um']
    tab = params['active_tab']

    if tab == 'Stripline':
        h_total_um = params['sl_gnd_um'] + params['sl_h2_um'] + params['sl_t_um'] + params['sl_h1_um'] + params['sl_gnd_um']
    elif tab == 'Embedded diffpair':
        h_total_um = params['edp_gnd_um'] + params['edp_h2_um'] + params['edp_t_um'] + params['edp_h1_um'] + params['edp_gnd_um']
    else:
        h_total_um = params['img_height_um']
    
    width_px = max(10, int(round(w_total_um / scale)))
    height_px = max(10, int(round(h_total_um / scale)))
    img_array = np.full((height_px, width_px, 3), COLORS['vacuum'], dtype=np.uint8)
    
    center_x_px = width_px / 2.0

    if tab == 'CPWG':
        t_cu_top = params['cpwg_t_top_um'] / scale
        t_d1 = params['cpwg_d1_um'] / scale
        t_cu_in1 = params['cpwg_t_in1_um'] / scale
        t_d2 = params['cpwg_d2_um'] / scale
        t_cu_in2 = params['cpwg_t_in2_um'] / scale
        t_d3 = params['cpwg_d3_um'] / scale
        t_cu_bot = params['cpwg_t_bot_um'] / scale
        t_sm = params['cpwg_sm_um'] / scale
        w_trace = params['cpwg_w_um'] / scale
        s_gap = params['cpwg_s_um'] / scale
        
        carve_w = w_trace + (s_gap * 2)
        carve_l = center_x_px - (carve_w / 2.0)
        carve_r = center_x_px + (carve_w / 2.0)
        trace_l = center_x_px - (w_trace / 2.0)
        trace_r = center_x_px + (w_trace / 2.0)

        curr_y = 0.0
        draw_rectangle(img_array, 0, width_px, curr_y, curr_y + t_cu_bot, COLORS['green_cu_gnd'], height_px); curr_y += t_cu_bot
        draw_rectangle(img_array, 0, width_px, curr_y, curr_y + t_d3, COLORS['fr4'], height_px); curr_y += t_d3
        draw_rectangle(img_array, 0, width_px, curr_y, curr_y + t_cu_in2, COLORS['green_cu_gnd'], height_px)
        draw_rectangle(img_array, carve_l, carve_r, curr_y, curr_y + t_cu_in2, COLORS['fr4'], height_px); curr_y += t_cu_in2
        draw_rectangle(img_array, 0, width_px, curr_y, curr_y + t_d2, COLORS['fr4'], height_px); curr_y += t_d2
        draw_rectangle(img_array, 0, width_px, curr_y, curr_y + t_cu_in1, COLORS['green_cu_gnd'], height_px)
        draw_rectangle(img_array, carve_l, carve_r, curr_y, curr_y + t_cu_in1, COLORS['fr4'], height_px); curr_y += t_cu_in1
        draw_rectangle(img_array, 0, width_px, curr_y, curr_y + t_d1, COLORS['fr4'], height_px); curr_y += t_d1
        draw_rectangle(img_array, 0, width_px, curr_y, curr_y + t_cu_top, COLORS['green_cu_gnd'], height_px)
        draw_rectangle(img_array, carve_l, carve_r, curr_y, curr_y + t_cu_top, COLORS['vacuum'], height_px)
        draw_rectangle(img_array, trace_l, trace_r, curr_y, curr_y + t_cu_top, COLORS['red_cu_p1v'], height_px)
        
        if t_sm > 0:
            ytc = curr_y + t_cu_top
            draw_rectangle(img_array, 0, carve_l, ytc, ytc + t_sm, COLORS['solder_mask'], height_px)
            draw_rectangle(img_array, carve_r, width_px, ytc, ytc + t_sm, COLORS['solder_mask'], height_px)
            draw_rectangle(img_array, trace_l, trace_r, ytc, ytc + t_sm, COLORS['solder_mask'], height_px)
            draw_rectangle(img_array, carve_l, trace_l, curr_y, curr_y + t_sm, COLORS['solder_mask'], height_px)
            draw_rectangle(img_array, trace_r, carve_r, curr_y, curr_y + t_sm, COLORS['solder_mask'], height_px)
            draw_rectangle(img_array, carve_l, carve_l + t_sm, curr_y + t_sm, ytc + t_sm, COLORS['solder_mask'], height_px)
            draw_rectangle(img_array, trace_l - t_sm, trace_l, curr_y + t_sm, ytc + t_sm, COLORS['solder_mask'], height_px)
            draw_rectangle(img_array, trace_r, trace_r + t_sm, curr_y + t_sm, ytc + t_sm, COLORS['solder_mask'], height_px)
            draw_rectangle(img_array, carve_r - t_sm, carve_r, curr_y + t_sm, ytc + t_sm, COLORS['solder_mask'], height_px)

    elif tab == 'Microstrip':
        t_gnd = params['ms_gnd_um'] / scale
        t_h = params['ms_h_um'] / scale
        t_cu = params['ms_t_um'] / scale
        t_sm = params['ms_sm_um'] / scale
        w_trace = params['ms_w_um'] / scale
        s_gap = params['ms_s_gap_um'] / scale
        
        carve_w = w_trace + (s_gap * 2)
        carve_l = center_x_px - (carve_w / 2.0)
        carve_r = center_x_px + (carve_w / 2.0)
        trace_l = center_x_px - (w_trace / 2.0)
        trace_r = center_x_px + (w_trace / 2.0)

        curr_y = 0.0
        draw_rectangle(img_array, 0, width_px, curr_y, curr_y + t_gnd, COLORS['green_cu_gnd'], height_px); curr_y += t_gnd
        draw_rectangle(img_array, 0, width_px, curr_y, curr_y + t_h, COLORS['fr4'], height_px); curr_y += t_h
        
        draw_rectangle(img_array, 0, carve_l, curr_y, curr_y + t_cu, COLORS['green_cu_gnd'], height_px)
        draw_rectangle(img_array, carve_r, width_px, curr_y, curr_y + t_cu, COLORS['green_cu_gnd'], height_px)
        draw_rectangle(img_array, trace_l, trace_r, curr_y, curr_y + t_cu, COLORS['red_cu_p1v'], height_px)
        
        if t_sm > 0:
            ytc = curr_y + t_cu
            draw_rectangle(img_array, 0, carve_l, ytc, ytc + t_sm, COLORS['solder_mask'], height_px)
            draw_rectangle(img_array, carve_r, width_px, ytc, ytc + t_sm, COLORS['solder_mask'], height_px)
            draw_rectangle(img_array, trace_l, trace_r, ytc, ytc + t_sm, COLORS['solder_mask'], height_px)
            draw_rectangle(img_array, carve_l, trace_l, curr_y, curr_y + t_sm, COLORS['solder_mask'], height_px)
            draw_rectangle(img_array, trace_r, carve_r, curr_y, curr_y + t_sm, COLORS['solder_mask'], height_px)
            draw_rectangle(img_array, carve_l, carve_l + t_sm, curr_y + t_sm, ytc + t_sm, COLORS['solder_mask'], height_px)
            draw_rectangle(img_array, trace_l - t_sm, trace_l, curr_y + t_sm, ytc + t_sm, COLORS['solder_mask'], height_px)
            draw_rectangle(img_array, trace_r, trace_r + t_sm, curr_y + t_sm, ytc + t_sm, COLORS['solder_mask'], height_px)
            draw_rectangle(img_array, carve_r - t_sm, carve_r, curr_y + t_sm, ytc + t_sm, COLORS['solder_mask'], height_px)

    elif tab == 'Stripline':
        t_gnd = params['sl_gnd_um'] / scale
        t_h2 = params['sl_h2_um'] / scale
        t_cu = params['sl_t_um'] / scale
        t_h1 = params['sl_h1_um'] / scale
        w_trace = params['sl_w_um'] / scale
        s_gap = params['sl_s_gap_um'] / scale
        
        carve_w = w_trace + (s_gap * 2)
        carve_l = center_x_px - (carve_w / 2.0)
        carve_r = center_x_px + (carve_w / 2.0)
        trace_l = center_x_px - (w_trace / 2.0)
        trace_r = center_x_px + (w_trace / 2.0)

        curr_y = 0.0
        draw_rectangle(img_array, 0, width_px, curr_y, curr_y + t_gnd, COLORS['green_cu_gnd'], height_px); curr_y += t_gnd
        draw_rectangle(img_array, 0, width_px, curr_y, curr_y + t_h2, COLORS['fr4'], height_px); curr_y += t_h2
        
        draw_rectangle(img_array, 0, carve_l, curr_y, curr_y + t_cu, COLORS['green_cu_gnd'], height_px)
        draw_rectangle(img_array, carve_r, width_px, curr_y, curr_y + t_cu, COLORS['green_cu_gnd'], height_px)
        draw_rectangle(img_array, carve_l, carve_r, curr_y, curr_y + t_cu, COLORS['fr4'], height_px) 
        draw_rectangle(img_array, trace_l, trace_r, curr_y, curr_y + t_cu, COLORS['red_cu_p1v'], height_px) 
        curr_y += t_cu
        
        draw_rectangle(img_array, 0, width_px, curr_y, curr_y + t_h1, COLORS['fr4'], height_px); curr_y += t_h1
        draw_rectangle(img_array, 0, width_px, curr_y, curr_y + t_gnd, COLORS['green_cu_gnd'], height_px)

    elif tab == 'Differential pair':
        t_gnd = params['dp_gnd_um'] / scale
        t_h = params['dp_h_um'] / scale
        t_cu = params['dp_t_um'] / scale
        t_sm = params['dp_sm_um'] / scale
        w_trace = params['dp_w_um'] / scale
        s_trace_gap = params['dp_s_um'] / scale
        s_gnd_gap = params['dp_s_gap_um'] / scale
        
        t1_l = center_x_px - (s_trace_gap / 2.0) - w_trace
        t1_r = center_x_px - (s_trace_gap / 2.0)
        t2_l = center_x_px + (s_trace_gap / 2.0)
        t2_r = center_x_px + (s_trace_gap / 2.0) + w_trace
        
        carve_l = t1_l - s_gnd_gap
        carve_r = t2_r + s_gnd_gap

        curr_y = 0.0
        draw_rectangle(img_array, 0, width_px, curr_y, curr_y + t_gnd, COLORS['green_cu_gnd'], height_px); curr_y += t_gnd
        draw_rectangle(img_array, 0, width_px, curr_y, curr_y + t_h, COLORS['fr4'], height_px); curr_y += t_h
        
        draw_rectangle(img_array, 0, carve_l, curr_y, curr_y + t_cu, COLORS['green_cu_gnd'], height_px)
        draw_rectangle(img_array, carve_r, width_px, curr_y, curr_y + t_cu, COLORS['green_cu_gnd'], height_px)
        
        color_t2 = COLORS['red_cu_p1v'] if is_even_mode else COLORS['blue_cu_m1v']
        draw_rectangle(img_array, t1_l, t1_r, curr_y, curr_y + t_cu, COLORS['red_cu_p1v'], height_px)
        draw_rectangle(img_array, t2_l, t2_r, curr_y, curr_y + t_cu, color_t2, height_px)
        
        if t_sm > 0:
            ytc = curr_y + t_cu
            draw_rectangle(img_array, 0, carve_l, ytc, ytc + t_sm, COLORS['solder_mask'], height_px) 
            draw_rectangle(img_array, carve_r, width_px, ytc, ytc + t_sm, COLORS['solder_mask'], height_px) 
            draw_rectangle(img_array, t1_l, t1_r, ytc, ytc + t_sm, COLORS['solder_mask'], height_px) 
            draw_rectangle(img_array, t2_l, t2_r, ytc, ytc + t_sm, COLORS['solder_mask'], height_px) 
            
            draw_rectangle(img_array, carve_l, t1_l, curr_y, curr_y + t_sm, COLORS['solder_mask'], height_px) 
            draw_rectangle(img_array, t1_r, t2_l, curr_y, curr_y + t_sm, COLORS['solder_mask'], height_px) 
            draw_rectangle(img_array, t2_r, carve_r, curr_y, curr_y + t_sm, COLORS['solder_mask'], height_px) 

            draw_rectangle(img_array, carve_l, carve_l + t_sm, curr_y + t_sm, ytc + t_sm, COLORS['solder_mask'], height_px)
            draw_rectangle(img_array, t1_l - t_sm, t1_l, curr_y + t_sm, ytc + t_sm, COLORS['solder_mask'], height_px)
            draw_rectangle(img_array, t1_r, t1_r + t_sm, curr_y + t_sm, ytc + t_sm, COLORS['solder_mask'], height_px)
            draw_rectangle(img_array, t2_l - t_sm, t2_l, curr_y + t_sm, ytc + t_sm, COLORS['solder_mask'], height_px)
            draw_rectangle(img_array, t2_r, t2_r + t_sm, curr_y + t_sm, ytc + t_sm, COLORS['solder_mask'], height_px)
            draw_rectangle(img_array, carve_r - t_sm, carve_r, curr_y + t_sm, ytc + t_sm, COLORS['solder_mask'], height_px)

    elif tab == 'Embedded diffpair':
        t_gnd = params['edp_gnd_um'] / scale
        t_h2 = params['edp_h2_um'] / scale
        t_cu = params['edp_t_um'] / scale
        t_h1 = params['edp_h1_um'] / scale
        w_trace = params['edp_w_um'] / scale
        s_trace_gap = params['edp_s_um'] / scale
        s_gnd_gap = params['edp_s_gap_um'] / scale
        
        t1_l = center_x_px - (s_trace_gap / 2.0) - w_trace
        t1_r = center_x_px - (s_trace_gap / 2.0)
        t2_l = center_x_px + (s_trace_gap / 2.0)
        t2_r = center_x_px + (s_trace_gap / 2.0) + w_trace
        
        carve_l = t1_l - s_gnd_gap
        carve_r = t2_r + s_gnd_gap

        curr_y = 0.0
        draw_rectangle(img_array, 0, width_px, curr_y, curr_y + t_gnd, COLORS['green_cu_gnd'], height_px); curr_y += t_gnd
        draw_rectangle(img_array, 0, width_px, curr_y, curr_y + t_h2, COLORS['fr4'], height_px); curr_y += t_h2
        
        draw_rectangle(img_array, 0, carve_l, curr_y, curr_y + t_cu, COLORS['green_cu_gnd'], height_px)
        draw_rectangle(img_array, carve_r, width_px, curr_y, curr_y + t_cu, COLORS['green_cu_gnd'], height_px)
        draw_rectangle(img_array, carve_l, carve_r, curr_y, curr_y + t_cu, COLORS['fr4'], height_px) 
        
        color_t2 = COLORS['red_cu_p1v'] if is_even_mode else COLORS['blue_cu_m1v']
        draw_rectangle(img_array, t1_l, t1_r, curr_y, curr_y + t_cu, COLORS['red_cu_p1v'], height_px) 
        draw_rectangle(img_array, t2_l, t2_r, curr_y, curr_y + t_cu, color_t2, height_px) 
        curr_y += t_cu
        
        draw_rectangle(img_array, 0, width_px, curr_y, curr_y + t_h1, COLORS['fr4'], height_px); curr_y += t_h1
        draw_rectangle(img_array, 0, width_px, curr_y, curr_y + t_gnd, COLORS['green_cu_gnd'], height_px)

    # Draw 2-pixel wide GND stitching traces on left and right edges,
    # connecting all GND layers to ensure atlc2 sees them as one net.
    # gnd_top_px is the top of the uppermost copper layer for each tab.
    if tab == 'CPWG':
        gnd_top_px = (params['cpwg_t_bot_um'] + params['cpwg_d3_um'] +
                      params['cpwg_t_in2_um'] + params['cpwg_d2_um'] +
                      params['cpwg_t_in1_um'] + params['cpwg_d1_um'] +
                      params['cpwg_t_top_um']) / scale
    elif tab == 'Microstrip':
        gnd_top_px = (params['ms_gnd_um'] + params['ms_h_um'] + params['ms_t_um']) / scale
    elif tab == 'Stripline':
        gnd_top_px = (params['sl_gnd_um'] + params['sl_h2_um'] + params['sl_t_um'] +
                      params['sl_h1_um'] + params['sl_gnd_um']) / scale
    elif tab == 'Differential pair':
        gnd_top_px = (params['dp_gnd_um'] + params['dp_h_um'] + params['dp_t_um']) / scale
    elif tab == 'Embedded diffpair':
        gnd_top_px = (params['edp_gnd_um'] + params['edp_h2_um'] + params['edp_t_um'] +
                      params['edp_h1_um'] + params['edp_gnd_um']) / scale
    else:
        gnd_top_px = height_px
    draw_rectangle(img_array, 0, 2, 0, gnd_top_px, COLORS['green_cu_gnd'], height_px)
    draw_rectangle(img_array, width_px - 2, width_px, 0, gnd_top_px, COLORS['green_cu_gnd'], height_px)

    return Image.fromarray(img_array, 'RGB')

# ==========================================
# --- ATLC2 RESULT PARSING ---
# ==========================================
def read_last_float_from_file(filepath):
    """
    Extract the last floating-point number from the last non-empty line of a file.

    ATLC2 appends result values to its output files as the simulation
    progresses.  The final value on the final line is always the converged
    result, so we scan backwards through lines to find it.

    Returns None if the file does not exist, is empty, or contains no numbers.
    """
    if not os.path.exists(filepath): return None
    try:
        with open(filepath, 'r') as f:
            content = f.read().strip()
            if not content: return None
            lines = content.split('\n')
            for line in reversed(lines):
                numbers = re.findall(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", line)
                if numbers:
                    return float(numbers[-1])
    except Exception:
        pass
    return None

def calculate_transmission_properties(sim_dir, project_name, freq_mhz):
    """
    Read ATLC2 result files and compute transmission line parameters.

    ATLC2 writes per-unit-length L, C, R and G values into separate text
    files.  This function reads those files, converts units, and applies the
    telegrapher's equations to derive the characteristic impedance Z0,
    attenuation constant alpha, velocity factor VF, and propagation velocity.

    The function is called repeatedly by poll_for_results() until all four
    base files are populated (ATLC2 writes them incrementally).

    Args:
        sim_dir      : directory where ATLC2 result files are written
        project_name : base filename without extension, used to locate files
        freq_mhz     : simulation frequency in MHz, used to compute omega

    Returns:
        tuple: (Z0_ohm, alpha_db_cm, vf, v_mm_ns, status_string)
               Returns (None, None, None, None, reason) if data is not yet
               available or if a calculation error occurred.
    """
    f_l = os.path.join(sim_dir, f"{project_name} Inductances.txt")
    f_c = os.path.join(sim_dir, f"{project_name} Capacitances.txt")
    f_r = os.path.join(sim_dir, f"{project_name} Resistances.txt")
    f_g = os.path.join(sim_dir, f"{project_name} Conductances.txt")
    f_v = os.path.join(sim_dir, f"{project_name} VFactors.txt")

    L_raw = read_last_float_from_file(f_l) 
    C_raw = read_last_float_from_file(f_c) 
    R_raw = read_last_float_from_file(f_r) 
    G_raw = read_last_float_from_file(f_g) 
    
    # Wait until all 4 base files are populated to proceed
    if None in (L_raw, C_raw, R_raw, G_raw):
        return None, None, None, None, "Files not fully populated yet."

    L = L_raw * 1e-6   
    C = C_raw * 1e-12  
    R = R_raw          
    G = G_raw          

    vf = read_last_float_from_file(f_v)
    if vf is None:
        try:
            speed_of_light = 299792458.0
            v_m_s = 1.0 / math.sqrt(L * C)
            vf = v_m_s / speed_of_light
        except ZeroDivisionError:
            vf = 0.0

    omega = 2.0 * math.pi * (freq_mhz * 1e6)
    Z_series = complex(R, omega * L)
    Y_shunt = complex(G, omega * C)
    
    Z0_complex = cmath.sqrt(Z_series / Y_shunt)
    Z0_mag = abs(Z0_complex)
    
    gamma = cmath.sqrt(Z_series * Y_shunt)
    alpha_np_m = gamma.real
    
    alpha_db_m = alpha_np_m * 8.6858896
    alpha_db_cm = alpha_db_m / 100.0
    v_mm_ns = vf * 299.792458
    
    return Z0_mag, alpha_db_cm, vf, v_mm_ns, "Success"

# ==========================================
# --- IPC-2141 EMPIRICAL PREDICTIONS ---
# ==========================================
def calculate_ipc_prediction(params):
    """
    Calculates analytical impedance approximations based on IPC-2141 equations.
    Provides targeted error strings if mathematical boundaries are crossed.
    """
    tab = params['active_tab']
    er = params['fr4_er']
    
    try:
        if tab == 'CPWG':
            w = params.get('cpwg_w_um')
            s = params.get('cpwg_s_um')
            h = (params.get('cpwg_d1_um', 0) + params.get('cpwg_t_in1_um', 0) +
                 params.get('cpwg_d2_um', 0) + params.get('cpwg_t_in2_um', 0) + 
                 params.get('cpwg_d3_um', 0))
                 
            if w <= 0 or h <= 0 or s <= 0: return "Invalid Dimensions"

            # Hilberg Approximation for complete elliptic integral ratio K(k)/K(k')
            def K_ratio(k):
                if k <= 0 or k >= 1: return 1e-9 # Prevent div by zero
                kp = math.sqrt(1.0 - k**2)
                if k <= 0.70710678:
                    return math.pi / math.log(2.0 * (1.0 + math.sqrt(kp)) / (1.0 - math.sqrt(kp)))
                else:
                    return math.log(2.0 * (1.0 + math.sqrt(k)) / (1.0 - math.sqrt(k))) / math.pi
                    
            a = w
            b = w + 2.0 * s
            
            k_val = a / b
            k1_val = math.tanh((math.pi * a) / (4.0 * h)) / math.tanh((math.pi * b) / (4.0 * h))
            
            K_ratio_k = K_ratio(k_val)
            K_ratio_k1 = K_ratio(k1_val)
            
            # Eff and Z0 calculation mapped exactly from the image
            e_eff = (1.0 + er * (1.0 / K_ratio_k) * K_ratio_k1) / (1.0 + (1.0 / K_ratio_k) * K_ratio_k1)
            z0 = (60.0 * math.pi / math.sqrt(e_eff)) * (1.0 / (K_ratio_k + K_ratio_k1))
            
            return f"Predicted Z0: ~{z0:.1f} \u03A9\n(Analytic Approx, ignores Solder Mask)"

        elif tab == 'Microstrip':
            w = params.get('ms_w_um')
            t = params.get('ms_t_um')
            h = params.get('ms_h_um')
            if w <= 0 or h <= 0: return "Invalid Dimensions"
            
            ratio = (5.98 * h) / (0.8 * w + t)
            if ratio <= 1.0:
                return "Prediction N/A: Trace too wide for IPC-2141 Approx"
                
            z0 = (87.0 / math.sqrt(er + 1.41)) * math.log(ratio)
            return f"Predicted Z0: ~{z0:.1f} \u03A9\n(IPC Approx, ignores Solder Mask & Coplanar GND)"
        
        elif tab == 'Stripline':
            w = params['sl_w_um']
            t = params['sl_t_um']
            b = params['sl_h1_um'] + params['sl_h2_um'] + t
            if w <= 0 or b <= 0: return "Invalid Dimensions"
            
            ratio = (1.9 * b) / (0.8 * w + t)
            if ratio <= 1.0:
                return "Prediction N/A: Trace too wide for IPC-2141 Approx"
                
            z0 = (60.0 / math.sqrt(er)) * math.log(ratio)
            return f"Predicted Z0: ~{z0:.1f} \u03A9\n(IPC Approx, ignores Coplanar GND)"
            
        elif tab == 'Differential pair':
            w = params['dp_w_um']
            t = params['dp_t_um']
            h = params['dp_h_um']
            s = params['dp_s_um']
            if w <= 0 or h <= 0 or s <= 0: return "Invalid Dimensions"
            
            ratio = (5.98 * h) / (0.8 * w + t)
            if ratio <= 1.0:
                return "Prediction N/A: Trace too wide for IPC-2141 Approx"
                
            z0 = (87.0 / math.sqrt(er + 1.41)) * math.log(ratio)
            zdiff = 2 * z0 * (1 - 0.48 * math.exp(-0.96 * (s / h)))
            return f"Predicted Zdiff: ~{zdiff:.1f} \u03A9\n(IPC Approx, ignores Solder Mask & Coplanar GND)"
            
        elif tab == 'Embedded diffpair':
            w = params['edp_w_um']
            t = params['edp_t_um']
            s = params['edp_s_um']
            b = params['edp_h1_um'] + params['edp_h2_um'] + t
            if w <= 0 or b <= 0 or s <= 0: return "Invalid Dimensions"
            
            ratio = (1.9 * b) / (0.8 * w + t)
            if ratio <= 1.0:
                return "Prediction N/A: Trace too wide for IPC-2141 Approx"
                
            z0 = (60.0 / math.sqrt(er)) * math.log(ratio)
            zdiff = 2 * z0 * (1 - 0.374 * math.exp(-2.9 * (s / b)))
            return f"Predicted Zdiff: ~{zdiff:.1f} \u03A9\n(IPC Approx, ignores Coplanar GND)"
            
    except Exception as e:
        return f"Prediction Error: {e}"
    return ""


# ==========================================
# --- GUI Setup and Action handlers ---
# ==========================================
def get_params_from_gui(input_dict, notebook_widget):
    """
    Read and validate all GUI input fields and return them as a params dict.

    Reads the currently active notebook tab to determine which structure is
    selected, then collects only the parameters relevant to that tab.  All
    values are converted to float and checked for negative values.

    Args:
        input_dict      : dict mapping parameter key strings to tkinter
                          StringVar / BooleanVar objects (gui_inputs in main)
        notebook_widget : the ttk.Notebook widget, used to query the active tab

    Returns:
        dict with all parameters needed by generate_image() and
        execute_atlc2_script_threaded(), or None if any field is invalid.
    """
    params_out = {}
    try:
        for key in ['scale', 'img_w_um', 'img_h_um', 'sim_freq', 'fr4_er', 'sm_er']:
            val = float(input_dict[key].get())
            if val < 0: raise ValueError(f"{key} cannot be negative.")

        params_out['scale_um_per_px'] = float(input_dict['scale'].get())
        params_out['img_width_um'] = float(input_dict['img_w_um'].get())
        params_out['img_height_um'] = float(input_dict['img_h_um'].get())
        params_out['sim_frequency_mhz'] = float(input_dict['sim_freq'].get())
        params_out['fr4_er'] = float(input_dict['fr4_er'].get())
        params_out['solder_mask_er'] = float(input_dict['sm_er'].get())
        params_out['filename'] = input_dict['save_path'].get()
        params_out['full_diff_sim'] = input_dict['full_diff_sim'].get()
        params_out['keep_intermediate'] = input_dict['keep_intermediate'].get()
        
        active_tab_text = notebook_widget.tab(notebook_widget.select(), "text")
        params_out['active_tab'] = active_tab_text
        
        def safe_get(param_keys):
            for k in param_keys:
                val = float(input_dict[k].get())
                if val < 0: raise ValueError(f"{k} cannot be negative.")
                params_out[k] = val

        if active_tab_text == "CPWG":
            safe_get(['cpwg_w_um', 'cpwg_s_um', 'cpwg_sm_um', 'cpwg_t_top_um',
                      'cpwg_d1_um', 'cpwg_t_in1_um', 'cpwg_d2_um', 'cpwg_t_in2_um',
                      'cpwg_d3_um', 'cpwg_t_bot_um'])
        elif active_tab_text == "Microstrip":
            safe_get(['ms_w_um', 'ms_s_gap_um', 'ms_sm_um', 'ms_t_um', 'ms_h_um', 'ms_gnd_um'])
        elif active_tab_text == "Stripline":
            safe_get(['sl_w_um', 'sl_s_gap_um', 'sl_t_um', 'sl_h1_um', 'sl_h2_um', 'sl_gnd_um'])
        elif active_tab_text == "Differential pair":
            safe_get(['dp_w_um', 'dp_s_um', 'dp_s_gap_um', 'dp_sm_um', 'dp_t_um', 'dp_h_um', 'dp_gnd_um'])
        elif active_tab_text == "Embedded diffpair":
            safe_get(['edp_w_um', 'edp_s_um', 'edp_s_gap_um', 'edp_t_um', 'edp_h1_um', 'edp_h2_um', 'edp_gnd_um'])

        return params_out
    except ValueError:
        return None

def create_labeled_entry(parent, row, label_text, default_value, width=6, trace_var_callback=None, start_col=0):
    """
    Create a label + entry widget pair in a grid layout.

    Also attaches a FocusOut validator that shows an error dialog if the user
    leaves the field empty or enters a negative value.

    Args:
        parent             : parent tkinter widget (e.g. a LabelFrame)
        row                : grid row index
        label_text         : text shown to the left of the entry box
        default_value      : initial value placed in the entry
        width              : entry box width in characters (default 6)
        trace_var_callback : optional function called on every keystroke,
                             used to trigger the live preview update
        start_col          : starting grid column (allows two columns of pairs)

    Returns:
        tk.StringVar bound to the entry widget
    """
    tk.Label(parent, text=label_text, anchor='w').grid(row=row, column=start_col, sticky='ew', padx=5, pady=2)
    var = tk.StringVar(value=str(default_value))
    if trace_var_callback:
        var.trace_add('write', trace_var_callback)
    entry = ttk.Entry(parent, textvariable=var, width=width)
    entry.grid(row=row, column=start_col+1, padx=5, pady=2)

    def on_focus_out(event):
        val = var.get().strip()
        try:
            if val == '':
                raise ValueError("Field cannot be empty.")
            f = float(val)
            if f < 0:
                raise ValueError("Value cannot be negative.")
        except ValueError as e:
            messagebox.showerror("Invalid Input", f'"{label_text.rstrip(":")}": {e}')
            entry.focus_set()

    entry.bind('<FocusOut>', on_focus_out)
    return var

def create_cpwg_tab(notebook, inputs_dict, trace_cb):
    """
    Build the "Coplanar Waveguide with Ground (CPWG) — 4-layer stackup" tab.

    Populates inputs_dict with StringVar objects keyed by parameter name.
    trace_cb is wired to every entry so the live preview updates on each
    keystroke.
    """
    tab = ttk.Frame(notebook)
    notebook.add(tab, text='CPWG')
    inputs_frame = ttk.Frame(tab, padding=5)
    inputs_frame.pack(fill='both', expand=True)
    inputs_frame.columnconfigure(0, weight=1)
    inputs_frame.columnconfigure(1, weight=1)

    frame_stack = ttk.LabelFrame(inputs_frame, text="Stackup (um)", padding=5)
    frame_stack.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
    inputs_dict['cpwg_sm_um']    = create_labeled_entry(frame_stack, 0, "Solder Mask (um):", DEFAULTS['cpwg_sm_um'], trace_var_callback=trace_cb)
    inputs_dict['cpwg_t_top_um'] = create_labeled_entry(frame_stack, 1, "Top Cu (um):", DEFAULTS['cpwg_t_top_um'], trace_var_callback=trace_cb)
    inputs_dict['cpwg_d1_um']    = create_labeled_entry(frame_stack, 2, "Dielectric 1 (um):", DEFAULTS['cpwg_d1_um'], trace_var_callback=trace_cb)
    inputs_dict['cpwg_t_in1_um'] = create_labeled_entry(frame_stack, 3, "L2 Cu (um):", DEFAULTS['cpwg_t_in1_um'], trace_var_callback=trace_cb)
    inputs_dict['cpwg_d2_um']    = create_labeled_entry(frame_stack, 4, "Dielectric 2 (um):", DEFAULTS['cpwg_d2_um'], trace_var_callback=trace_cb)
    inputs_dict['cpwg_t_in2_um'] = create_labeled_entry(frame_stack, 5, "L3 Cu (um):", DEFAULTS['cpwg_t_in2_um'], trace_var_callback=trace_cb)
    inputs_dict['cpwg_d3_um']    = create_labeled_entry(frame_stack, 6, "Dielectric 3 (um):", DEFAULTS['cpwg_d3_um'], trace_var_callback=trace_cb)
    inputs_dict['cpwg_t_bot_um'] = create_labeled_entry(frame_stack, 7, "Bottom Cu (um):", DEFAULTS['cpwg_t_bot_um'], trace_var_callback=trace_cb)

    frame_geom = ttk.LabelFrame(inputs_frame, text="Geometry", padding=5)
    frame_geom.grid(row=0, column=1, sticky='nsew', padx=5, pady=5)
    inputs_dict['cpwg_w_um'] = create_labeled_entry(frame_geom, 0, "Trace Width (um):", DEFAULTS['cpwg_w_um'], trace_var_callback=trace_cb)
    inputs_dict['cpwg_s_um'] = create_labeled_entry(frame_geom, 1, "Gap to GND (um):", DEFAULTS['cpwg_s_um'], trace_var_callback=trace_cb)

def create_microstrip_tab(notebook, inputs_dict, trace_cb):
    """
    Build the "Microstrip — single signal trace above a ground plane" tab.

    Populates inputs_dict with StringVar objects keyed by parameter name.
    trace_cb is wired to every entry so the live preview updates on each
    keystroke.
    """
    tab = ttk.Frame(notebook)
    notebook.add(tab, text='Microstrip')
    inputs_frame = ttk.Frame(tab, padding=5)
    inputs_frame.pack(fill='both', expand=True)
    inputs_frame.columnconfigure(0, weight=1)
    inputs_frame.columnconfigure(1, weight=1)

    frame_stack = ttk.LabelFrame(inputs_frame, text="Stackup (um)", padding=5)
    frame_stack.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
    inputs_dict['ms_sm_um']  = create_labeled_entry(frame_stack, 0, "Solder Mask (um):", DEFAULTS['ms_sm_um'], trace_var_callback=trace_cb)
    inputs_dict['ms_t_um']   = create_labeled_entry(frame_stack, 1, "Top Cu (um):", DEFAULTS['ms_t_um'], trace_var_callback=trace_cb)
    inputs_dict['ms_h_um']   = create_labeled_entry(frame_stack, 2, "Dielectric H (um):", DEFAULTS['ms_h_um'], trace_var_callback=trace_cb)
    inputs_dict['ms_gnd_um'] = create_labeled_entry(frame_stack, 3, "Bottom Cu (um):", DEFAULTS['ms_gnd_um'], trace_var_callback=trace_cb)
    
    frame_geom = ttk.LabelFrame(inputs_frame, text="Geometry", padding=5)
    frame_geom.grid(row=0, column=1, sticky='nsew', padx=5, pady=5)
    inputs_dict['ms_w_um']     = create_labeled_entry(frame_geom, 0, "Trace Width (um):", DEFAULTS['ms_w_um'], trace_var_callback=trace_cb)
    inputs_dict['ms_s_gap_um'] = create_labeled_entry(frame_geom, 1, "Gap to GND (um):", DEFAULTS['ms_s_gap_um'], trace_var_callback=trace_cb)

def create_stripline_tab(notebook, inputs_dict, trace_cb):
    """
    Build the "Stripline — signal trace embedded between two ground planes" tab.

    Populates inputs_dict with StringVar objects keyed by parameter name.
    trace_cb is wired to every entry so the live preview updates on each
    keystroke.
    """
    tab = ttk.Frame(notebook)
    notebook.add(tab, text='Stripline')
    inputs_frame = ttk.Frame(tab, padding=5)
    inputs_frame.pack(fill='both', expand=True)
    inputs_frame.columnconfigure(0, weight=1)
    inputs_frame.columnconfigure(1, weight=1)

    frame_stack = ttk.LabelFrame(inputs_frame, text="Stackup (um)", padding=5)
    frame_stack.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
    inputs_dict['sl_gnd_um'] = create_labeled_entry(frame_stack, 0, "Top/Bot Cu (um):", DEFAULTS['sl_gnd_um'], trace_var_callback=trace_cb)
    inputs_dict['sl_h1_um']  = create_labeled_entry(frame_stack, 1, "Top Diel H1 (um):", DEFAULTS['sl_h1_um'], trace_var_callback=trace_cb)
    inputs_dict['sl_t_um']   = create_labeled_entry(frame_stack, 2, "Trace Cu (um):", DEFAULTS['sl_t_um'], trace_var_callback=trace_cb)
    inputs_dict['sl_h2_um']  = create_labeled_entry(frame_stack, 3, "Bot Diel H2 (um):", DEFAULTS['sl_h2_um'], trace_var_callback=trace_cb)
    
    frame_geom = ttk.LabelFrame(inputs_frame, text="Geometry", padding=5)
    frame_geom.grid(row=0, column=1, sticky='nsew', padx=5, pady=5)
    inputs_dict['sl_w_um'] = create_labeled_entry(frame_geom, 0, "Trace Width (um):", DEFAULTS['sl_w_um'], trace_var_callback=trace_cb)
    inputs_dict['sl_s_gap_um'] = create_labeled_entry(frame_geom, 1, "Gap to GND (um):", DEFAULTS['sl_s_gap_um'], trace_var_callback=trace_cb)

def create_diffpair_tab(notebook, inputs_dict, trace_cb):
    """
    Build the "Differential pair microstrip — two coupled surface traces" tab.

    Populates inputs_dict with StringVar objects keyed by parameter name.
    trace_cb is wired to every entry so the live preview updates on each
    keystroke.
    """
    tab = ttk.Frame(notebook)
    notebook.add(tab, text='Differential pair')
    inputs_frame = ttk.Frame(tab, padding=5)
    inputs_frame.pack(fill='both', expand=True)
    inputs_frame.columnconfigure(0, weight=1)
    inputs_frame.columnconfigure(1, weight=1)

    frame_stack = ttk.LabelFrame(inputs_frame, text="Stackup (um)", padding=5)
    frame_stack.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
    inputs_dict['dp_sm_um']  = create_labeled_entry(frame_stack, 0, "Solder Mask (um):", DEFAULTS['dp_sm_um'], trace_var_callback=trace_cb)
    inputs_dict['dp_t_um']   = create_labeled_entry(frame_stack, 1, "Top Cu (um):", DEFAULTS['dp_t_um'], trace_var_callback=trace_cb)
    inputs_dict['dp_h_um']   = create_labeled_entry(frame_stack, 2, "Dielectric H (um):", DEFAULTS['dp_h_um'], trace_var_callback=trace_cb)
    inputs_dict['dp_gnd_um'] = create_labeled_entry(frame_stack, 3, "Bottom Cu (um):", DEFAULTS['dp_gnd_um'], trace_var_callback=trace_cb)
    
    frame_geom = ttk.LabelFrame(inputs_frame, text="Geometry", padding=5)
    frame_geom.grid(row=0, column=1, sticky='nsew', padx=5, pady=5)
    inputs_dict['dp_w_um'] = create_labeled_entry(frame_geom, 0, "Trace Width (um):", DEFAULTS['dp_w_um'], trace_var_callback=trace_cb)
    inputs_dict['dp_s_um'] = create_labeled_entry(frame_geom, 1, "Trace Gap S (um):", DEFAULTS['dp_s_um'], trace_var_callback=trace_cb)
    inputs_dict['dp_s_gap_um'] = create_labeled_entry(frame_geom, 2, "Gap to GND (um):", DEFAULTS['dp_s_gap_um'], trace_var_callback=trace_cb)

def create_embedded_diffpair_tab(notebook, inputs_dict, trace_cb):
    """
    Build the "Embedded differential pair stripline — two coupled buried traces" tab.

    Populates inputs_dict with StringVar objects keyed by parameter name.
    trace_cb is wired to every entry so the live preview updates on each
    keystroke.
    """
    tab = ttk.Frame(notebook)
    notebook.add(tab, text='Embedded diffpair')
    inputs_frame = ttk.Frame(tab, padding=5)
    inputs_frame.pack(fill='both', expand=True)
    inputs_frame.columnconfigure(0, weight=1)
    inputs_frame.columnconfigure(1, weight=1)

    frame_stack = ttk.LabelFrame(inputs_frame, text="Stackup (um)", padding=5)
    frame_stack.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
    inputs_dict['edp_gnd_um'] = create_labeled_entry(frame_stack, 0, "Top/Bot Cu (um):", DEFAULTS['edp_gnd_um'], trace_var_callback=trace_cb)
    inputs_dict['edp_h1_um']  = create_labeled_entry(frame_stack, 1, "Top Diel (um):", DEFAULTS['edp_h1_um'], trace_var_callback=trace_cb)
    inputs_dict['edp_t_um']   = create_labeled_entry(frame_stack, 2, "Trace Cu (um):", DEFAULTS['edp_t_um'], trace_var_callback=trace_cb)
    inputs_dict['edp_h2_um']  = create_labeled_entry(frame_stack, 3, "Bot Diel (um):", DEFAULTS['edp_h2_um'], trace_var_callback=trace_cb)
    
    frame_geom = ttk.LabelFrame(inputs_frame, text="Geometry", padding=5)
    frame_geom.grid(row=0, column=1, sticky='nsew', padx=5, pady=5)
    inputs_dict['edp_w_um'] = create_labeled_entry(frame_geom, 0, "Trace Width (um):", DEFAULTS['edp_w_um'], trace_var_callback=trace_cb)
    inputs_dict['edp_s_um'] = create_labeled_entry(frame_geom, 1, "Trace Gap S (um):", DEFAULTS['edp_s_um'], trace_var_callback=trace_cb)
    inputs_dict['edp_s_gap_um'] = create_labeled_entry(frame_geom, 2, "Gap to GND (um):", DEFAULTS['edp_s_gap_um'], trace_var_callback=trace_cb)

def execute_atlc2_script_threaded(params, root_window, results_label, image_abs_path, btn_run):
    """
    Launch an ATLC2 simulation in a background thread and display the results.

    This function performs all simulation I/O without blocking the GUI:
      1. Writes MoreColors.txt so ATLC2 knows the Er values for FR4 and
         solder mask (identified by their pixel colours in the PNG).
      2. Writes a StartupScript.txt that tells ATLC2 which PNG to open,
         the pixel size, frequency, and thread count.
      3. Launches atlc2.exe as a subprocess and optionally repositions its
         windows next to the Python GUI using the Windows API (snap_windows).
      4. Polls the result files once per second until ATLC2 has finished
         writing them, then computes and displays Z0, attenuation, and
         velocity factor.
      5. If "Keep Intermediate Results" is unchecked, terminates ATLC2 and
         deletes all generated files (PNGs, scripts, result TXTs) via cleanup().

    For differential pairs with "Full Diff Sim" enabled, two sequential
    simulations are run: even mode first, then odd mode.  Z0 is derived from
    the geometric mean of Zodd and Zeven.

    Args:
        params          : dict from get_params_from_gui()
        root_window     : the root tk.Tk window (used for after() callbacks
                          and window position queries)
        results_label   : tk.Label widget where result text is displayed
        image_abs_path  : absolute path to the PNG that was just saved
        btn_run         : the Run button widget, disabled during simulation
                          and re-enabled when done
    """
    exe_path = os.path.abspath('atlc2.exe')
    if not os.path.exists(exe_path):
        messagebox.showerror("Error", f"ATLC2 executable not found at:\n{exe_path}")
        return

    sim_dir = os.path.dirname(image_abs_path)
    png_filename = os.path.basename(image_abs_path)
    project_name = os.path.splitext(png_filename)[0] 
    
    is_diff_pair = "diff" in params['active_tab'].lower()
    is_full_diff = params['full_diff_sim']
    keep_intermediate = params['keep_intermediate']
    
    if is_diff_pair and is_full_diff:
        prefixes = [f"{project_name}_odd", f"{project_name}_even"]
    else:
        prefixes = [project_name]

    for prefix in prefixes:
        files_to_delete = [
            f"{prefix} Inductances.txt",
            f"{prefix} Capacitances.txt",
            f"{prefix} Resistances.txt",
            f"{prefix} Conductances.txt",
            f"{prefix} VFactors.txt"
        ]
        for f in files_to_delete:
            fpath = os.path.join(sim_dir, f)
            if os.path.exists(fpath):
                try: os.remove(fpath)
                except Exception: pass 

    morecolors_path = os.path.join(sim_dir, "MoreColors.txt")
    morecolors_content = f"""| Custom Materials File generated by Python Script
| red green blue use Ohms Er tanDelta Mu name
223 247 136 insul 1000000 {params['fr4_er']} 0.018 1 FR4_Custom
188 127 96 insul 1000000 {params['solder_mask_er']} 0.03 1 SolderMask_Custom
"""
    try:
        with open(morecolors_path, "w") as f:
            f.write(morecolors_content)
    except Exception as e:
        messagebox.showerror("Script Error", f"Could not write MoreColors.txt:\n{e}")
        return

    scale_mm = params['scale_um_per_px'] / 1000.0 

    # Calculate optimal threads: ~75% of available logical cores
    total_cores = os.cpu_count() or 4  # Fallback to 4 if detection fails
    optimal_threads = max(1, int(total_cores * 0.75))

    def write_script(proj_name, png_name):
        """
        Write the ATLC2 StartupScript.txt for a single simulation run.

        ATLC2 reads this file on startup.  Key commands:
          LRS  — Load and Run Simulation (performs the 2D FEM solve)
          CGP  — Calculate and write per-unit-length RLGC parameters to files
          save — save the solved field image as a new PNG

        Args:
            proj_name : output project name (also used as the result file prefix)
            png_name  : input PNG filename that ATLC2 should open
        """
        script_content = f"""| Auto-generated ATLC2 Startup Script
name {proj_name}
open {png_name}
pixel {scale_mm}mm
frequency {params['sim_frequency_mhz']}
threads {optimal_threads}
LRS
CGP
name {proj_name}-solved
save
beep
"""
        script_path = os.path.join(sim_dir, "StartupScript.txt")
        with open(script_path, "w") as f:
            f.write(script_content)

    btn_run.config(state=tk.DISABLED)

    gui_x = root_window.winfo_x()
    gui_y = root_window.winfo_y()
    gui_w = root_window.winfo_width()
    target_x = gui_x + gui_w + 10  
    target_y = gui_y

    def snap_windows(proc, offset_x=0, offset_y=0):
        """
        Move the ATLC2 window to appear beside the Python GUI (Windows only).

        Polls for up to 3 seconds for ATLC2's main window and control panel
        to appear, then repositions them using SetWindowPos so they don't
        overlap the Python GUI.  offset_x/offset_y allow staggering two
        simultaneous ATLC2 instances (even + odd mode) so both are visible.

        Args:
            proc     : subprocess.Popen object for the running atlc2.exe
            offset_x : horizontal pixel offset from the default snap position
            offset_y : vertical pixel offset from the default snap position
        """
        main_hwnd = None
        ctrl_hwnd = None
        for _ in range(15): 
            time.sleep(0.2)
            def enum_window_callback(hwnd, _):
                nonlocal main_hwnd, ctrl_hwnd
                w_pid = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(w_pid))
                
                if w_pid.value == proc.pid and ctypes.windll.user32.IsWindowVisible(hwnd):
                    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    buff = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value.lower()
                    
                    if "control panel" in title:
                        ctrl_hwnd = hwnd
                    elif title.strip() != "":
                        main_hwnd = hwnd
                return True
            
            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            ctypes.windll.user32.EnumWindows(EnumWindowsProc(enum_window_callback), 0)
            if main_hwnd and ctrl_hwnd: break

        if main_hwnd:
            ctypes.windll.user32.SetWindowPos(main_hwnd, 0, target_x + offset_x, target_y + offset_y, 0, 0, 0x0015)
            if ctrl_hwnd:
                rect = RECT()
                ctypes.windll.user32.GetWindowRect(main_hwnd, ctypes.byref(rect))
                main_bottom = rect.bottom
                ctypes.windll.user32.SetWindowPos(ctrl_hwnd, 0, target_x + offset_x, main_bottom, 0, 0, 0x0015)

    def poll_for_results(proj_name):
        """
        Block the simulation thread until ATLC2 result files are ready.

        Checks calculate_transmission_properties() once per second for up to
        one hour (3600 attempts).  Returns as soon as a valid result is found.

        Args:
            proj_name : project name prefix used to locate the result files

        Returns:
            tuple: same as calculate_transmission_properties(), or
                   (None, None, None, None, "Simulation timed out.") on timeout
        """
        max_attempts = 3600 
        for _ in range(max_attempts):
            time.sleep(1)
            res = calculate_transmission_properties(sim_dir, proj_name, params['sim_frequency_mhz'])
            if res[0] is not None:
                return res
        return None, None, None, None, "Simulation timed out."

    def cleanup(procs):
        """Terminate atlc2 processes and delete all intermediate files."""
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        intermediate = []
        if is_diff_pair and is_full_diff:
            used_prefixes = [f"{project_name}_odd", f"{project_name}_even"]
            used_pngs = [f"{project_name}_odd.png", f"{project_name}_even.png"]
        else:
            used_prefixes = [project_name]
            used_pngs = [png_filename]
        for prefix in used_prefixes:
            for suffix in [" Inductances.txt", " Capacitances.txt", " Resistances.txt",
                           " Conductances.txt", " VFactors.txt", "-solved Inductances.txt",
                           "-solved Capacitances.txt", "-solved Resistances.txt",
                           "-solved Conductances.txt", "-solved VFactors.txt"]:
                intermediate.append(os.path.join(sim_dir, f"{prefix}{suffix}"))
        for png in used_pngs:
            intermediate.append(os.path.join(sim_dir, png))
        intermediate.append(os.path.join(sim_dir, "StartupScript.txt"))
        intermediate.append(os.path.join(sim_dir, "MoreColors.txt"))
        for fpath in intermediate:
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except Exception:
                    pass

    def run_simulation():
        try:
            if is_diff_pair and is_full_diff:
                root_window.after(0, lambda: results_label.config(text=f"Simulation '{project_name}'\nRunning Even Mode in background...", fg="blue"))
                write_script(f"{project_name}_even", f"{project_name}_even.png")
                proc_even = subprocess.Popen([exe_path], cwd=sim_dir)
                snap_windows(proc_even, 0, 0)
                
                z_even_run, _, _, _, msg_e = poll_for_results(f"{project_name}_even")
                if z_even_run is None:
                    root_window.after(0, lambda: results_label.config(text=f"Even Mode Simulation Failed:\n{msg_e}", fg="red"))
                    root_window.after(0, lambda: btn_run.config(state=tk.NORMAL))
                    return

                root_window.after(0, lambda: results_label.config(text=f"Simulation '{project_name}'\nRunning Odd Mode in background...", fg="blue"))
                write_script(f"{project_name}_odd", f"{project_name}_odd.png")
                proc_odd = subprocess.Popen([exe_path], cwd=sim_dir)
                snap_windows(proc_odd, 30, 30)
                
                z_odd_run, alpha, vf, v_mm_ns, msg_o = poll_for_results(f"{project_name}_odd")
                if z_odd_run is None:
                    root_window.after(0, lambda: results_label.config(text=f"Odd Mode Simulation Failed:\n{msg_o}", fg="red"))
                    root_window.after(0, lambda: btn_run.config(state=tk.NORMAL))
                    return
                
                z_diff = z_odd_run
                z_odd = z_diff / 2.0
                z_comm = z_even_run
                z_even = z_comm * 2.0
                z0 = math.sqrt(z_odd * z_even)
                
                res_text = (f"Simulation Complete!\n\n"
                            f"Z0 (Characteristic): {z0:.2f} \u03A9\n"
                            f"Zdiff (Differential): {z_diff:.2f} \u03A9\n"
                            f"Zcomm (Common-mode): {z_comm:.2f} \u03A9\n"
                            f"Zodd: {z_odd:.2f} \u03A9  |  Zeven: {z_even:.2f} \u03A9\n\n"
                            f"Attenuation: {alpha:.5f} dB/cm\n"
                            f"Velocity Factor: {vf:.4f} ({v_mm_ns:.2f} mm/ns)")
                root_window.after(0, lambda: results_label.config(text=res_text, fg="green"))
                if not keep_intermediate:
                    cleanup([proc_even, proc_odd])
                root_window.after(0, lambda: btn_run.config(state=tk.NORMAL))

            elif is_diff_pair and not is_full_diff:
                root_window.after(0, lambda: results_label.config(text=f"Simulation '{project_name}' running in background...", fg="blue"))
                write_script(project_name, png_filename)
                proc = subprocess.Popen([exe_path], cwd=sim_dir)
                snap_windows(proc, 0, 0)
                
                z_odd_run, alpha, vf, v_mm_ns, msg = poll_for_results(project_name)
                
                if z_odd_run is not None:
                    z_diff = z_odd_run
                    z_odd = z_diff / 2.0
                    res_text = (f"Simulation Complete!\n\n"
                                f"Zdiff (Differential): {z_diff:.2f} \u03A9\n"
                                f"Zodd (Single-ended): {z_odd:.2f} \u03A9\n"
                                f"Attenuation: {alpha:.5f} dB/cm\n"
                                f"Velocity Factor: {vf:.4f} ({v_mm_ns:.2f} mm/ns)")
                    root_window.after(0, lambda: results_label.config(text=res_text, fg="green"))
                else:
                    root_window.after(0, lambda: results_label.config(text=f"Simulation Failed:\n{msg}", fg="red"))
                if not keep_intermediate:
                    cleanup([proc])
                root_window.after(0, lambda: btn_run.config(state=tk.NORMAL))

            else:
                root_window.after(0, lambda: results_label.config(text=f"Simulation '{project_name}' running in background...", fg="blue"))
                write_script(project_name, png_filename)
                proc = subprocess.Popen([exe_path], cwd=sim_dir)
                snap_windows(proc, 0, 0)
                
                z0, alpha, vf, v_mm_ns, msg = poll_for_results(project_name)
                
                if z0 is not None:
                    res_text = (f"Simulation Complete!\n\n"
                                f"Z0 (Impedance): {z0:.2f} \u03A9\n"
                                f"Attenuation: {alpha:.5f} dB/cm\n"
                                f"Velocity Factor: {vf:.4f} ({v_mm_ns:.2f} mm/ns)")
                    root_window.after(0, lambda: results_label.config(text=res_text, fg="green"))
                else:
                    root_window.after(0, lambda: results_label.config(text=f"Simulation Failed:\n{msg}", fg="red"))
                if not keep_intermediate:
                    cleanup([proc])
                root_window.after(0, lambda: btn_run.config(state=tk.NORMAL))
                
        except Exception as e:
            err_msg = f"Execution Error:\n{e}"
            root_window.after(0, lambda: results_label.config(text=err_msg, fg="red"))
            root_window.after(0, lambda: btn_run.config(state=tk.NORMAL))

    sim_thread = threading.Thread(target=run_simulation, daemon=True)
    sim_thread.start()

def generate_icon():
    """
    Generate the application window icon programmatically using generate_image().

    Creates a microstrip cross-section with coplanar GND and solder mask using
    carefully chosen parameters that produce a readable image at small icon sizes.
    The source image is 200x200 px (1 um/px scale), which Pillow then resamples
    into a multi-resolution .ico file containing 16x16, 32x32, 48x48 and 256x256
    layers — the standard set expected by Windows.

    The .ico file is written to a temp file and loaded via root.iconbitmap().
    If anything fails the error is silently swallowed so a missing icon never
    prevents the application from starting.

    Returns:
        Path to the generated .ico file, or None on failure.
    """
    try:
        icon_params = {
            'active_tab':      'Microstrip',
            'scale_um_per_px': 1.0,
            'img_width_um':    200.0,
            'img_height_um':   200.0,
            # Stackup chosen for visual clarity at small sizes:
            'ms_gnd_um':       20.0,   # thin bottom ground plane
            'ms_h_um':         80.0,   # dielectric — fills most of the canvas
            'ms_t_um':         15.0,   # thin signal copper
            'ms_sm_um':        15.0,   # solder mask visible over trace and GND wings
            'ms_w_um':         80.0,   # wide trace — 40% of image width, reads at 16px
            'ms_s_gap_um':     20.0,   # narrow gap so coplanar GND is clearly visible
        }
        img = generate_image(icon_params)

        # Pillow saves a proper multi-resolution .ico when given a sizes list
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix='.ico', delete=False)
        tmp.close()
        img.save(tmp.name, format='ICO', sizes=[(16,16),(32,32),(48,48),(256,256)])
        return tmp.name
    except Exception:
        return None

def main_gui():
    """
    Build and run the main application window.

    Layout overview:
      Left side  — ttk.Notebook with one tab per transmission line type,
                   plus a General Simulation Settings frame below it, and
                   a Filename + Run button row at the bottom.
      Right side — live cross-section preview image, IPC-2141 prediction
                   text, and the simulation results readout.

    The left and right sides are placed in a plain ttk.Frame container using
    pack(side='left') so there is no resizable sash between them.

    The live preview is debounced: a 300 ms timer is reset on every keystroke
    so the (relatively slow) image generation only runs when the user pauses
    typing.
    """
    root = tk.Tk()
    root.title(program_name)
    root.geometry("850x530")

    # Generate and set window icon from a programmatically drawn microstrip image
    _icon_path = generate_icon()
    if _icon_path:
        try:
            root.iconbitmap(_icon_path)
        except Exception:
            pass


    style = ttk.Style()
    style.theme_use('clam') 
    gui_inputs = {}

    container = ttk.Frame(root)
    container.pack(fill='both', expand=True, padx=5, pady=5)

    left_frame = ttk.Frame(container)
    right_frame = ttk.Frame(container, padding=10)
    left_frame.pack(side='left', fill='y')
    right_frame.pack(side='left', fill='both', expand=True)

    debounce_timer = None
    preview_img_tk = None

    def update_live_preview(*args):
        nonlocal debounce_timer, preview_img_tk
        if debounce_timer:
            root.after_cancel(debounce_timer)
        
        def render_preview():
            nonlocal preview_img_tk
            params = get_params_from_gui(gui_inputs, notebook)
            if params is None: return
            
            # --- 1. Safely generate prediction text ---
            try:
                prediction_txt = calculate_ipc_prediction(params)
            except Exception as e:
                prediction_txt = f"Prediction Error: {e}"
            lbl_prediction.config(text=prediction_txt)

            # --- 2. Safely render image ---
            try:
                img_obj = generate_image(params, is_even_mode=False)
                max_w, max_h = 320, 180
                img_w, img_h = img_obj.size
                scale = min(max_w / img_w, max_h / img_h, 1.0)
                
                new_w = max(1, int(img_w * scale))
                new_h = max(1, int(img_h * scale))
                
                img_preview = img_obj.resize((new_w, new_h), Image.Resampling.NEAREST)
                preview_img_tk = ImageTk.PhotoImage(img_preview)
                lbl_preview_canvas.config(image=preview_img_tk)
            except Exception:
                pass 

        debounce_timer = root.after(300, render_preview)

    def on_tab_changed(event=None):
        try:
            active_tab_text = notebook.tab(notebook.select(), "text")
            
            if "diff" in active_tab_text.lower():
                chk_full_diff.config(state=tk.NORMAL)
            else:
                chk_full_diff.config(state=tk.DISABLED)
                
            current_name = gui_inputs['save_path'].get()
            default_names = ["microstrip.png", "stripline.png", "cpwg.png", "differential_pair.png", "embedded_diffpair.png"]
            if current_name in default_names or current_name == "":
                new_name = active_tab_text.lower().replace(' ', '_') + ".png"
                gui_inputs['save_path'].delete(0, tk.END)
                gui_inputs['save_path'].insert(0, new_name)
                
            update_live_preview()
        except Exception:
            pass

    notebook = ttk.Notebook(left_frame)
    notebook.pack(fill='both', expand=True, padx=5, pady=5)
    notebook.configure(height=240)
    notebook.bind('<<NotebookTabChanged>>', on_tab_changed)

    common_frame = ttk.LabelFrame(left_frame, text="General Simulation Settings", padding=5)
    common_frame.pack(fill='x', padx=5, pady=5)
    
    gui_inputs['scale'] = create_labeled_entry(common_frame, 0, "Image Scale (um/pixel):", DEFAULTS['scale_um_per_px'], trace_var_callback=update_live_preview)
    gui_inputs['img_w_um'] = create_labeled_entry(common_frame, 1, "Total Image Width (um):", DEFAULTS['img_width_um'], trace_var_callback=update_live_preview)
    gui_inputs['img_h_um'] = create_labeled_entry(common_frame, 2, "Total Image Height (um): ", DEFAULTS['img_height_um'], trace_var_callback=update_live_preview)
    gui_inputs['sim_freq'] = create_labeled_entry(common_frame, 3, "Frequency (MHz):", DEFAULTS['sim_frequency_mhz'])
    
    gui_inputs['fr4_er'] = create_labeled_entry(common_frame, 0, "FR4 Er:", DEFAULTS['fr4_er'], start_col=2, trace_var_callback=update_live_preview)
    gui_inputs['sm_er'] = create_labeled_entry(common_frame, 1, "Solder Mask Er: ", DEFAULTS['solder_mask_er'], start_col=2, trace_var_callback=update_live_preview)
    
    gui_inputs['full_diff_sim'] = tk.BooleanVar(value=False)
    chk_full_diff = ttk.Checkbutton(common_frame, text="Full Diff Sim (Odd + Even)", variable=gui_inputs['full_diff_sim']) # Both even and odd modes
    chk_full_diff.grid(row=2, column=2, columnspan=2, sticky='w', padx=5, pady=2)
    chk_full_diff.config(state=tk.DISABLED)

    gui_inputs['keep_intermediate'] = tk.BooleanVar(value=False)
    chk_keep = ttk.Checkbutton(common_frame, text="Keep Intermediate Results", variable=gui_inputs['keep_intermediate'])
    chk_keep.grid(row=3, column=2, columnspan=2, sticky='w', padx=5, pady=2) 

    create_microstrip_tab(notebook, gui_inputs, update_live_preview)
    create_stripline_tab(notebook, gui_inputs, update_live_preview)
    create_cpwg_tab(notebook, gui_inputs, update_live_preview)
    create_diffpair_tab(notebook, gui_inputs, update_live_preview)
    create_embedded_diffpair_tab(notebook, gui_inputs, update_live_preview)
    
    action_frame = ttk.Frame(left_frame, padding=10)
    action_frame.pack(fill='x', side='bottom', pady=5)

    ttk.Label(action_frame, text="Filename:").pack(side='left', padx=(0, 5))
    gui_inputs['save_path'] = ttk.Entry(action_frame, width=30)
    gui_inputs['save_path'].insert(0, DEFAULTS['filename'])
    gui_inputs['save_path'].pack(side='left', padx=(0, 10))

    btn_run = ttk.Button(action_frame, text="Run ATLC2 Simulation", state=tk.DISABLED)
    btn_run.pack(side='left', ipady=5, ipadx=5)

    lbl_preview_title = tk.Label(right_frame, text="Live Cross-Section Preview", font=("Arial", 12, "bold"))
    lbl_preview_title.pack(anchor='n', pady=5)
    
    lbl_preview_canvas = tk.Label(right_frame, bg="gray")
    lbl_preview_canvas.pack(fill='both', expand=True, padx=5, pady=5)

    lbl_prediction = tk.Label(right_frame, text="Prediction: ...", justify="center", font=("Arial", 9, "italic"), fg="#555")
    lbl_prediction.pack(anchor='n', pady=(0, 15), fill='x')

    lbl_results = tk.Label(right_frame, text="Ready to simulate.", justify="center", font=("Consolas", 11), fg="black", wraplength=450)
    lbl_results.pack(anchor='s', pady=15, fill='x')

    def on_run_simulation_click():
        params = get_params_from_gui(gui_inputs, notebook)
        if params is None: return
        
        save_name = params['filename']
        if not save_name.lower().endswith('.png'): save_name += '.png'
        abs_path = os.path.abspath(save_name)
        sim_dir = os.path.dirname(abs_path)
        project_name = os.path.splitext(os.path.basename(abs_path))[0] 
        
        is_diff_pair = "diff" in params['active_tab'].lower()
        is_full_diff = params['full_diff_sim']
        keep_intermediate = params['keep_intermediate']
        
        try:
            if is_diff_pair and is_full_diff:
                img_odd = generate_image(params, is_even_mode=False)
                img_even = generate_image(params, is_even_mode=True)
                img_odd.save(os.path.join(sim_dir, f"{project_name}_odd.png"), format='PNG')
                img_even.save(os.path.join(sim_dir, f"{project_name}_even.png"), format='PNG')
            elif is_diff_pair and not is_full_diff:
                img_odd = generate_image(params, is_even_mode=False)
                img_odd.save(abs_path, format='PNG')
            else:
                img = generate_image(params)
                img.save(abs_path, format='PNG')
                
            execute_atlc2_script_threaded(params, root, lbl_results, abs_path, btn_run)
            
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save image:\n{e}")

    btn_run.config(command=on_run_simulation_click, state=tk.NORMAL)
    
    def check_executable():
        if not os.path.exists("atlc2.exe"):
            root.withdraw() 
            dlg = tk.Toplevel(root)
            dlg.title("ATLC2 Missing")
            dlg.geometry("500x200")
            dlg.protocol("WM_DELETE_WINDOW", lambda: (dlg.destroy(), root.deiconify())) 
            
            ttk.Label(dlg, text="atlc2.exe was not found in the current directory!", font=("Arial", 10, "bold")).pack(pady=(20, 5))
            ttk.Label(dlg, text="This executable is required to run the simulations.\nYou can download it automatically or visit the homepage.").pack(pady=5)
            
            btn_frame = ttk.Frame(dlg)
            btn_frame.pack(pady=15)
            
            def open_web():
                webbrowser.open("http://www.hdtvprimer.com/kq6qv/atlc2.html")
            
            def do_download():
                btn_down.config(state=tk.DISABLED, text="Downloading...")
                def task():
                    try:
                        urllib.request.urlretrieve("http://www.hdtvprimer.com/KQ6QV/Win64/atlc2.exe", "atlc2.exe")
                        dlg.after(0, lambda: messagebox.showinfo("Success", "atlc2.exe downloaded successfully!"))
                        dlg.after(0, dlg.destroy)
                        dlg.after(0, root.deiconify)
                    except Exception as e:
                        dlg.after(0, lambda: messagebox.showerror("Download Error", f"Failed to download:\n{e}"))
                        dlg.after(0, lambda: btn_down.config(state=tk.NORMAL, text="Download atlc2.exe (Win64)"))
                threading.Thread(target=task, daemon=True).start()
                
            btn_web = ttk.Button(btn_frame, text="Open ATLC2 Homepage", command=open_web)
            btn_web.grid(row=0, column=0, padx=5)
            
            btn_down = ttk.Button(btn_frame, text="Download atlc2.exe (Win64)", command=do_download)
            btn_down.grid(row=0, column=1, padx=5)
            
            btn_skip = ttk.Button(btn_frame, text="Skip (Image Gen Only)", command=lambda: (dlg.destroy(), root.deiconify()))
            btn_skip.grid(row=0, column=2, padx=5)
    
    root.after(100, check_executable)
    on_tab_changed() 
    root.mainloop()

if __name__ == '__main__':
    main_gui()
