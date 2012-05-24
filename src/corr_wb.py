"""
Setup and unique functionality for the wide-band correlator modes. A wideband correlator's FPGAs process all digitised data, which is a multiple of the FPGA clock rates.
"""
"""
Revisions:
2011-07-07  PVP  Initial revision.
"""
import construct, corr_functions

# f-engine control register
register_fengine_control = construct.BitStruct('control',
    construct.Padding(32 - 20 - 1),             # 21 - 31
    construct.Flag('tvgsel_noise'),             # 20
    construct.Flag('tvgsel_fdfs'),              # 19
    construct.Flag('tvgsel_pkt'),               # 18
    construct.Flag('tvgsel_ct'),                # 17
    construct.Flag('tvg_en'),                   # 16
    construct.Padding(16 - 13 - 1),             # 14 - 15
    construct.Flag('adc_protect_disable'),      # 13
    construct.Flag('flasher_en'),               # 12
    construct.Padding(12 - 9 - 1),              # 10 - 11
    construct.Flag('gbe_enable'),               # 9
    construct.Flag('gbe_rst'),                  # 8
    construct.Padding(8 - 3 - 1),               # 4 - 7
    construct.Flag('clr_status'),               # 3
    construct.Flag('arm'),                      # 2
    construct.Flag('soft_sync'),                # 1
    construct.Flag('mrst'))                     # 0

# f-engine status
register_fengine_fstatus = construct.BitStruct('fstatus0',
    construct.Padding(32 - 29 - 1),     # 30 - 31
    construct.BitField("sync_val", 2),  # 28 - 29
    construct.Padding(28 - 17 - 1),     # 18 - 27
    construct.Flag('xaui_lnkdn'),       # 17
    construct.Flag('xaui_over'),        # 16
    construct.Padding(16 - 6 - 1),      # 7 - 15
    construct.Flag('dram_err'),         # 6
    construct.Flag('clk_err'),          # 5
    construct.Flag('adc_disabled'),     # 4
    construct.Flag('ct_error'),         # 3
    construct.Flag('adc_overrange'),    # 2
    construct.Flag('fft_overrange'),    # 1
    construct.Flag('quant_overrange'))  # 0

# x-engine control register
register_xengine_control = construct.BitStruct('ctrl',
    construct.Padding(32 - 16 - 1),     # 17 - 31
    construct.Flag('gbe_out_enable'),   # 16
    construct.Flag('gbe_rst'),          # 15
    construct.Padding(15 - 12 - 1),     # 13 - 14
    construct.Flag('flasher_en'),       # 12
    construct.Flag('gbe_out_rst'),      # 11
    construct.Flag('loopback_mux_rst'), # 10
    construct.Flag('gbe_enable'),       # 9
    construct.Flag('cnt_rst'),          # 8
    construct.Flag('clr_status'),       # 7
    construct.Padding(7 - 0 - 1),       # 1 - 6
    construct.Flag('vacc_rst'))         # 0

# x-engine status
register_xengine_status = construct.BitStruct('xstatus0',
    construct.Padding(32 - 18 - 1),     # 19 - 31
    construct.Flag('gbe_lnkdn'),        # 18
    construct.Flag('xeng_err'),         # 17
    construct.Padding(17 - 5 - 1),      # 6 - 16
    construct.Flag('vacc_err'),         # 5
    construct.Flag('rx_bad_pkt'),       # 4
    construct.Flag('rx_bad_frame'),     # 3
    construct.Flag('tx_over'),          # 2
    construct.Flag('pkt_reord_err'),    # 1
    construct.Flag('pack_err'))         # 0

# x-engine tvg control
register_xengine_tvg_sel = construct.BitStruct('tvg_sel',
    construct.Padding(32 - 1 - 2 - 2 - 6),  # 11 - 31
    construct.BitField("vacc_tvg_sel", 6),  # 5 - 10
    construct.BitField("xeng_tvg_sel", 2),  # 3 - 4
    construct.BitField("descr_tvg_sel", 2), # 1 - 2
    construct.Flag('xaui_tvg_sel'))         # 0

snap_xengine_rx = construct.BitStruct("snap_rx0",
    construct.Padding(128 - 64 - 16 - 5 - 28 - 15),
    construct.BitField("ant", 15), 
    construct.BitField("mcnt", 28),
    construct.Flag("loop_ack"),
    construct.Flag("gbe_ack"),
    construct.Flag("valid"),
    construct.Flag("eof"),
    construct.Flag("flag"),
    construct.BitField("ip_addr", 16),
    construct.BitField("data", 64))

snap_xengine_gbe_rx = construct.BitStruct("snap_gbe_rx0",
    construct.Padding(128 - 64 - 32 - 7),
    construct.Flag("led_up"),
    construct.Flag("led_rx"),
    construct.Flag("eof"),
    construct.Flag("bad_frame"),
    construct.Flag("overflow"),
    construct.Flag("valid"),
    construct.Flag("ack"),
    construct.BitField("ip_addr", 32),
    construct.BitField("data", 64))

snap_xengine_gbe_tx = construct.BitStruct("snap_gbe_tx0",
        construct.Padding(128 - 64 - 32 - 6), 
        construct.Flag("eof"),
        construct.Flag("link_up"),
        construct.Flag("led_tx"),
        construct.Flag("tx_full"),
        construct.Flag("tx_over"),
        construct.Flag("valid"),
        construct.BitField("ip_addr", 32),
        construct.BitField("data", 64))

# the snap block immediately after the x-engine
snap_xengine_vacc = construct.BitStruct("snap_vacc0", construct.BitField("data", 32))

# the xaui snap block on the f-engine - this is just after packetisation
snap_fengine_xaui = construct.BitStruct("snap_xaui0",
    construct.Padding(128 - 1 - 3 - 1 - 1 - 3 - 64),
    construct.Flag("link_down"),
    construct.Padding(3),
    construct.Flag("mrst"),
    construct.Padding(1),
    construct.Flag("eof"),
    construct.Flag("sync"),
    construct.Flag("hdr_valid"),
    construct.BitField("data", 64))

snap_fengine_gbe_tx = construct.BitStruct("snap_gbe_tx0",
    construct.Padding(128 - 64 - 32 - 6), 
    construct.Flag("eof"),
    construct.Flag("link_up"),
    construct.Flag("led_tx"),
    construct.Flag("tx_full"),
    construct.Flag("tx_over"),
    construct.Flag("valid"),
    construct.BitField("ip_addr", 32),
    construct.BitField("data", 64))


def feng_status_get(c, ant_str):
    """Reads and decodes the status register for a given antenna. Adds some other bits 'n pieces relating to Fengine status."""
    #'sync_val': 28:30, #This is the number of clocks of sync pulse offset for the demux-by-four ADC 1PPS.
    ffpga_n, xfpga_n, fxaui_n, xxaui_n, feng_input = c.get_ant_str_location(ant_str)
    rv = corr_functions.read_masked_register([c.ffpgas[ffpga_n]], register_fengine_fstatus, names = ['fstatus%i' % feng_input])[0]
    if rv['xaui_lnkdn'] or rv['xaui_over'] or rv['clk_err'] or rv['ct_error'] or rv['fft_overrange']:
        rv['lru_state']='fail'
    elif rv['adc_overrange'] or rv['adc_disabled']:
        rv['lru_state']='warning'
    else:
        rv['lru_state']='ok'
    return rv

# end
