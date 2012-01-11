"""
Setup and unique functionality for the narrow-band correlator modes.

Revisions:
2011-07-07  PVP  Initial revision.
"""
import numpy, struct, construct, corr_functions, snap

coarse_snap_name = 'crs_snap_d'
fine_snap_name = 'fine_snap_d'

# f-engine status
register_fengine_fstatus = construct.BitStruct('fstatus0',
    construct.BitField('coarse_bits', 5),       # 27 - 31
    construct.BitField('fine_bits', 5),         # 22 - 26
    construct.BitField('sync_val', 2),          # 20 - 21
    construct.Padding(2),                       # 18 - 19
    construct.Flag('xaui_lnkdn'),               # 17
    construct.Flag('xaui_over'),                # 16
    construct.Padding(9),                       # 7 - 15
    construct.Flag('clk_err'),                  # 6
    construct.Flag('adc_disabled'),             # 5
    construct.Flag('ct_error'),                 # 4
    construct.Flag('adc_overrange'),            # 3
    construct.Flag('fine_fft_overrange'),       # 2
    construct.Flag('coarse_fft_overrange'),     # 1
    construct.Flag('quant_overrange'))          # 0

# f-engine coarse control
register_fengine_coarse_control = construct.BitStruct('coarse_ctrl',
    construct.Padding(32 - 10 - 10 - 3),        # 23 - 31
    construct.BitField('fft_shift', 10),        # 13 - 22
    construct.BitField('channel_select', 10),   # 3 - 12
    construct.Flag('mixer_select'),             # 2
    construct.Flag('snap_data_select'),         # 1
    construct.Flag('snap_pol_select'))          # 0

# f-engine fine control
register_fengine_fine_control = construct.BitStruct('fine_ctrl',
    construct.Padding(32 - 13 - 2 - 2 - 1),     # 18 - 31
    construct.BitField('fft_shift', 13),        # 5 - 17
    construct.BitField('quant_snap_select', 2), # 3 - 4
    construct.BitField('snap_data_select', 2),  # 1 - 2
    construct.Flag('snap_pol_select'))          # 0

# f-engine control
register_fengine_control = construct.BitStruct('control',
    construct.Padding(10),                   # 22 - 31
    construct.Flag('fine_chan_tvg_post'),   # 21
    construct.Flag('adc_tvg'),              # 20
    construct.Flag('fdfs_tvg'),             # 19
    construct.Flag('packetiser_tvg'),       # 18
    construct.Flag('ct_tvg'),               # 17
    construct.Flag('tvg_en'),               # 16
    construct.Padding(4),                   # 12 - 15
    construct.Flag('flasher_en'),           # 11
    construct.Flag('adc_protect_disable'),  # 10
    construct.Flag('gbe_enable'),           # 9
    construct.Flag('gbe_rst'),              # 8
    construct.Padding(4),                   # 4 - 7
    construct.Flag('clr_status'),           # 3
    construct.Flag('arm'),                  # 2
    construct.Flag('man_sync'),             # 1
    construct.Flag('sys_rst'))              # 0

# x-engine control
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

# the snap_rx block on the x-engine
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

# the raw gbe rx snap block on the x-engine
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

# the snap block immediately after the x-engine
snap_xengine_vacc = construct.BitStruct("snap_vacc0", construct.BitField("data", 32))

# the xaui snap block on the f-engine - this is just after packetisation
snap_fengine_xaui = construct.BitStruct("snap_xaui",
    construct.Padding(128 - 1 - 3 - 1 - 1 - 3 - 64),
    construct.Flag("link_down"),
    construct.Padding(3),
    construct.Flag("mrst"),
    construct.Padding(1),
    construct.Flag("eof"),
    construct.Flag("sync"),
    construct.Flag("hdr_valid"),
    construct.BitField("data", 64))

# set the coarse FFT per-stage shift
def fft_shift_coarse_set_all(correlator, shift = -1):
    if shift < 0:
        shift = correlator.config['fft_shift_coarse']
    corr_functions.write_masked_register(correlator.ffpgas, register_fengine_coarse_control, fft_shift = shift)
    correlator.syslogger.info('Set coarse FFT shift patterns on all F-engines to 0x%x.' % shift)
#def coarse_fft_shift_get_all(correlator):
#  rv={}
#  for ant in range(correlator.config['n_ants']):
#    for pol in correlator.config['pols']:
#      ffpga_n, xfpga_n, fxaui_n, xxaui_n, feng_input = correlator.get_ant_location(ant, pol)
#      rv[(ant, pol)] = correlator.ffpgas[ffpga_n].read_uint('crs_fft_shift')
#  return rv

# set the fine FFT per-stage shift
def fft_shift_fine_set_all(correlator, shift = -1):
    if shift < 0:
        shift = correlator.config['fft_shift_fine']
    corr_functions.write_masked_register(correlator.ffpgas, register_fengine_fine_control, fft_shift = shift)
    correlator.syslogger.info('Set fine FFT shift patterns on all F-engines to 0x%x.' % shift)

def fft_shift_get_all(correlator):
    rv = {}
    for in_n, ant_str in enumerate(correlator.config._get_ant_mapping_list()):
        ffpga_n, xfpga_n, fxaui_n, xxaui_n, feng_input = correlator.get_ant_str_location(ant_str)
        coarse_ctrl = corr_functions.read_masked_register([correlator.ffpgas[ffpga_n]], register_fengine_coarse_control)
        fine_ctrl = corr_functions.read_masked_register([correlator.ffpgas[ffpga_n]], register_fengine_fine_control)
        rv[ant_str] = [coarse_ctrl[0]['fft_shift'], fine_ctrl[0]['fft_shift']]
    return rv

def feng_status_get(c, ant_str):
    """Reads and decodes the status register for a given antenna. Adds some other bits 'n pieces relating to Fengine status."""
    ffpga_n, xfpga_n, fxaui_n, xxaui_n, feng_input = c.get_ant_str_location(ant_str)
    rv = corr_functions.read_masked_register([c.ffpgas[ffpga_n]], register_fengine_fstatus, names = ['fstatus%i' % feng_input])[0]
    if rv['xaui_lnkdn'] or rv['xaui_over'] or rv['clk_err'] or rv['ct_error'] or rv['fine_fft_overrange'] or rv['coarse_fft_overrange']:
        rv['lru_state']='fail'
    elif rv['adc_overrange']:
        rv['lru_state']='warning'
    else:
        rv['lru_state']='ok'
    return rv

def get_coarse_fft_snap(correlator, ant_str):
    # interpret the ant_string
    (ffpga_n, xfpga_n, fxaui_n, xxaui_n, feng_input) = correlator.get_ant_str_location(ant_str)
    # select the data from the coarse fft
    fpga = correlator.ffpgas[ffpga_n]
    corr_functions.write_masked_register([fpga], register_fengine_coarse_control, snap_data_select = 0)
    data = fpga.snapshot_get(dev_name = coarse_snap_name, man_trig = False, man_valid = False, wait_period = 3, offset = -1, circular_capture = False, get_extra_val = False)
    unpacked_scrambled = list(struct.unpack('>%iI' % (len(data['data']) / 4), data['data']))
    # re-arrange the data sensibly - for FFT data it's complex 16.15 fixed point signed data
    unpacked = []
    for ctr in range(0, len(unpacked_scrambled), 4):
        unpacked.append(unpacked_scrambled[ctr + 0])
        unpacked.append(unpacked_scrambled[ctr + 1])
        unpacked.append(unpacked_scrambled[ctr + 2])
        unpacked.append(unpacked_scrambled[ctr + 3])
    # make the actual complex numbers
    coarse_d  = []
    for ctr in range(0, len(unpacked)):
        num = unpacked[ctr]
        numR = numpy.int16(num >> 16)
        numI = numpy.int16(num & 0x0000ffff)
        coarse_d.append(numR + (1j * numI))
    return coarse_d

def get_fine_fft_snap(correlator, ant_str):
    # interpret the ant_string
    (ffpga_n, xfpga_n, fxaui_n, xxaui_n, feng_input) = correlator.get_ant_str_location(ant_str)
    # select the data from the fine fft
    fpga = correlator.ffpgas[ffpga_n]
    corr_functions.write_masked_register([fpga], register_fengine_fine_control, snap_data_select = 0, quant_snap_select = 0)
    data = fpga.snapshot_get(dev_name = fine_snap_name, man_trig = False, man_valid = False, wait_period = 3, offset = -1, circular_capture = False, get_extra_val = False)
    unpacked = list(struct.unpack('>%iI' % (len(data['data']) / 4), data['data']))
    # re-arrange the data sensibly - for FFT data it's complex 16.15 fixed point signed data
    # make the actual complex numbers
    d  = []
    for ctr in range(0, len(unpacked)):
        num = unpacked[ctr]
        numR = numpy.int16(num >> 16)
        numI = numpy.int16(num & 0x0000ffff)
        d.append(numR + (1j * numI))
    return d

def get_ct_snap(correlator, offset = -1):
    corr_functions.write_masked_register(correlator.ffpgas, register_fengine_fine_control, quant_snap_select = 2)
    raw = snap.snapshots_get(correlator.ffpgas, dev_names = fine_snap_name, man_trig = False, man_valid = False, wait_period = 3, offset = offset, circular_capture = False)
    chan_values = []
    for index, d in enumerate(raw['data']):
        up = list(struct.unpack('>%iI' % (len(d) / 4), d))
        values = [[], []]
        for value in up:
            # two freq channel values for the same freq-channel, both pols
            # will have to use the offset to get multiple freq channels
            p00 = value >> 24
            p10 = (value >> 16) & 0xff
            p01 = (value >> 8) & 0xff
            p11 = value & 0xff
            def extract8bit(v8):
                r = (v8 & ((2**8) - (2**4))) >> 4
                i = (v8 & ((2**4) - (2**0)))
                return r + (1j * i)
            values[0].append(value >> 24)
            values[0].append((value >> 8) & 0xff)
            values[1].append((value >> 16) & 0xff)
            values[1].append(value & 0xff)
        chan_values.append({'fpga_index': index, 'data': values})
    return chan_values
# end
