"""
A module for controlling and receiving data from a CASPER_N correlator.

Implements interfaces for controlling a CASPER_N correlator and verifying correct operation.
Used primarily for by the PAPER array project.

Author: Jason Manley, Aaron Parsons
Email: jason_manley at hotmail.com, aparsons at astron.berkeley.edu
Revisions:
"""
import cn_conf, katcp_wrapper, log_handlers, corr_functions, corr_wb, corr_nb, corr_ddc, scroll, katadc, iadc, termcolors, rx, sim, snap

