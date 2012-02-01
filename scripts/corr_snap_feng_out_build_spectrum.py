#!/usr/bin/env python

'''
Grabs the contents of "snap_xaui" on the F engines and rebuilds the spectrum.
Plots it if you ask it to.
Assumes 4 bit values for power calculations.
Assumes the correlator is already initialsed and running etc.

Author: Paul Prozesky

Revisions:
2012-01-25: JRM Added support for snap_10gbe_tx for correlators without XAUI links.
2011-09-12: PVP Initial version.
'''
import corr, time, numpy, struct, sys, logging

def exit_fail():
    print 'FAILURE DETECTED. Log entries:\n',
    c.log_handler.printMessages()
    print "Unexpected error:", sys.exc_info()
    try:
        c.disconnect_all()
    except: pass
    raise
    exit()

def exit_clean():
    try:
        c.disconnect_all()
    except: pass
    exit()

def print_packet_info_basic(server, count, d):
    #print '[%s @ %4i]: %016X' % (server, count, d.data),
    print '[%s @ %4i] [%d]: %016X' % (server, count, d.ip_addr, d.data),
    if d.eof: print '[EOF]',
    if d.link_down: print '[LINK DOWN]',
    if d.mrst: print '[MRST]',
    if d.sync: print '[SYNC]',
    if d.hdr_valid: print '[HDR]',
    if d.tx_over: print '[TX OVER]',
    if d.tx_full: print '[TX FULL]',
    if d.led_tx: print '[LED TX]',
    if d.link_up: print '[LINK UP]',
    print '' 

def print_10gbe_pkt_info_basic(server, count, d):
    print '' 

def print_packet_info(server, header_index, length, unpacked, mcount):
    print '[%s] [Pkt@ %4i Len: %2i]     (MCNT %16u ANT: %1i, Freq: %4i)  RMS: X: %1.2f Y: %1.2f.  {X: %1.2f+%1.2fj (%2.1f & %2.1f bits), Y:%1.2f+%1.2fj (%2.1f & %2.1f bits)} {Pk: X,Y: %1.2f,%1.2f (%2.1f,%2.1f bits)}' % \
        (server,\
        header_index,\
        length,\
        unpacked['pkt_mcnt'],\
        unpacked['pkt_ant'],\
        unpacked['pkt_mcnt'] % mcount,\
        unpacked['rms_polQ'],\
        unpacked['rms_polI'],\
        unpacked['level_polQ_r'],\
        unpacked['level_polQ_i'],\
        unpacked['ave_bits_used_Q_r'],\
        unpacked['ave_bits_used_Q_i'],\
        unpacked['level_polI_r'],\
        unpacked['level_polI_i'],\
        unpacked['ave_bits_used_I_r'],\
        unpacked['ave_bits_used_I_i'],\
        unpacked['pk_polQ'],\
        unpacked['pk_polI'],\
        unpacked['pk_bits_used_Q'],\
        unpacked['pk_bits_used_I'])

def feng_unpack(f, hdr_index, pkt_len, skip_indices):
    pkt_64bit = data[f]['data'][hdr_index].data #struct.unpack('>Q',bram_dmp['bram_msb'][f][(4*hdr_index):(4*hdr_index)+4]+bram_dmp['bram_lsb'][f][(4*hdr_index):(4*hdr_index)+4])[0]
    pkt_mcnt = (pkt_64bit & ((2**64)-(2**16)))>>16
    pkt_ant  = pkt_64bit & ((2**16)-1)
    pkt_freq = pkt_mcnt % n_chans
    sum_polQ_r = 0
    sum_polQ_i = 0
    sum_polI_r = 0
    sum_polI_i = 0
    pk_polQ = 0
    pk_polI = 0
    raw_data = []
    #average the packet contents - ignore first entry (header)
    for pkt_index in range(1,(pkt_len)):
        abs_index = hdr_index + pkt_index
        if skip_indices.count(abs_index)>0: 
            #print 'Skipped %i'%abs_index
            continue
        pkt_64bit = data[f]['data'][abs_index].data
        raw_data.append(pkt_64bit)
        for offset in range(0,64,16):
            polQ_r = (pkt_64bit & ((2**(offset+16)) - (2**(offset+12))))>>(offset+12)
            polQ_i = (pkt_64bit & ((2**(offset+12)) - (2**(offset+8))))>>(offset+8)
            polI_r = (pkt_64bit & ((2**(offset+8)) - (2**(offset+4))))>>(offset+4)
            polI_i = (pkt_64bit & ((2**(offset+4)) - (2**(offset))))>>offset
            qr_4b=float(((numpy.int8(polQ_r << 4)>> 4)))/(2**binary_point)
            qi_4b=float(((numpy.int8(polQ_i << 4)>> 4)))/(2**binary_point)
            ir_4b=float(((numpy.int8(polI_r << 4)>> 4)))/(2**binary_point)
            ii_4b=float(((numpy.int8(polI_i << 4)>> 4)))/(2**binary_point)
            #square each number and then sum it
            sum_polQ_r += qr_4b**2
            sum_polQ_i += qi_4b**2
            sum_polI_r += ir_4b**2
            sum_polI_i += ii_4b**2
            if (qr_4b > pk_polQ): pk_polQ = qr_4b
            if (qi_4b > pk_polQ): pk_polQ = qi_4b
            if (ir_4b > pk_polI): pk_polI = ir_4b
            if (ii_4b > pk_polI): pk_polI = ii_4b
    num_accs = (pkt_len-len(skip_indices))*(64/16)
    level_polQ_r = numpy.sqrt(float(sum_polQ_r)/ num_accs)
    level_polQ_i = numpy.sqrt(float(sum_polQ_i)/ num_accs)
    level_polI_r = numpy.sqrt(float(sum_polI_r)/ num_accs)
    level_polI_i = numpy.sqrt(float(sum_polI_i)/ num_accs)
    rms_polQ = numpy.sqrt(((level_polQ_r)**2)  +  ((level_polQ_i)**2))
    rms_polI = numpy.sqrt(((level_polI_r)**2)  +  ((level_polI_i)**2))
    #For bit counting, multiply by two (num_bits is 4, not 3 where bin point is) to account for fact that it's signed numbers, so amplitude of 1/16 is actually using +1/16 and -1/16.
    #To prevent log of zero, we check first.
    if pk_polQ < 1.0/(2**num_bits):  pk_bits_used_Q = 0
    else:  pk_bits_used_Q = numpy.log2(pk_polQ*(2**(num_bits)))
    if pk_polI < 1.0/(2**num_bits):  pk_bits_used_I = 0
    else:  pk_bits_used_I = numpy.log2(pk_polI*(2**(num_bits)))
    if level_polQ_r < 1.0/(2**num_bits): ave_bits_used_Q_r = 0
    else:  ave_bits_used_Q_r = numpy.log2(level_polQ_r*(2**(num_bits)))
    if level_polQ_i < 1.0/(2**num_bits):  ave_bits_used_Q_i = 0
    else:  ave_bits_used_Q_i = numpy.log2(level_polQ_i*(2**(num_bits)))
    if level_polI_r < 1.0/(2**num_bits):  ave_bits_used_I_r = 0
    else:  ave_bits_used_I_r = numpy.log2(level_polI_r*(2**(num_bits)))
    if level_polI_i < 1.0/(2**num_bits):  ave_bits_used_I_i = 0
    else: ave_bits_used_I_i = numpy.log2(level_polI_i*(2**(num_bits)))
    return {'raw_packets': raw_data,\
            'pkt_mcnt': pkt_mcnt,\
            'pkt_ant':pkt_ant,\
            'pkt_freq':pkt_freq,\
            'rms_polQ':rms_polQ,\
            'rms_polI':rms_polI,\
            'level_polQ_r':level_polQ_r,\
            'level_polQ_i':level_polQ_i,\
            'level_polI_r':level_polI_r,\
            'level_polI_i':level_polI_i,\
            'pk_polQ':pk_polQ,\
            'pk_polI':pk_polI,\
            'pk_bits_used_Q':pk_bits_used_Q,\
            'pk_bits_used_I':pk_bits_used_I,\
            'ave_bits_used_Q_r':ave_bits_used_Q_r,\
            'ave_bits_used_Q_i':ave_bits_used_Q_i,\
            'ave_bits_used_I_r':ave_bits_used_I_r,\
            'ave_bits_used_I_i':ave_bits_used_I_i}

def process_packets(c, f_index, data, spectrum, report):
    fsrv = c.fsrvs[f_index]
    #print fsrv + ': '
    report['pkt_total'] = 0
    pkt_hdr_idx = -1
    for i, d in enumerate(data):
        if opts.verbose:
            print_packet_info_basic(fsrv, i, d)
        if d.link_down:
            print '[%s] LINK DOWN AT %i' % (fsrv, i)
        elif d.hdr_valid:
            pkt_hdr_idx = i
            # skip_indices records positions in XAUI data which are ADC updates and should not be counted towards standard data.
            skip_indices = []
            if opts.verbose:
                print 'HEADER RECEIVED INDEX %i' % pkt_hdr_idx
        elif d.eof:
            # skip the first packet entry which has no header (snap block triggered on sync)
            if pkt_hdr_idx < 0:
                pkt_hdr_idx=i+1
                skip_indices = []
                continue
            pkt_len = i - pkt_hdr_idx + 1
            feng_unpkd_pkt = feng_unpack(f_index, pkt_hdr_idx, pkt_len, skip_indices)
            #print feng_unpkd_pkt['raw_packets']
            print_packet_info(server = fsrv, header_index = pkt_hdr_idx, length = pkt_len - len(skip_indices), unpacked = feng_unpkd_pkt, mcount = n_chans)
            if feng_unpkd_pkt['pkt_ant'] != f_index:
                raise RuntimeError('How did we get a packet from fengine %i read from fengine %i?' % (feng_unpkd_pkt['pkt_ant'], f_index))
            spectrum[0][feng_unpkd_pkt['pkt_freq']] += feng_unpkd_pkt['rms_polQ']
            spectrum[1][feng_unpkd_pkt['pkt_freq']]+= feng_unpkd_pkt['rms_polI']
            if opts.verbose: print ''
            pkt_hdr_idx=i+1
            skip_indices = []
            # packet_len is length of data, not including header
            if pkt_len - len(skip_indices) != (packet_len + 1):
                print 'MALFORMED PACKET! of length %i starting at index %i' % (pkt_len - len(skip_indices), i)
                print 'len of skip_indices: %i:' % len(skip_indices), skip_indices
                if not report.has_key('Malformed packets'):
                    report['Malformed packets'] = 1
                else: 
                    report['Malformed packets'] += 1
            if not report.has_key('pkt_ant_%i' % feng_unpkd_pkt['pkt_ant']):
                report['pkt_ant_%i' % feng_unpkd_pkt['pkt_ant']] = 1
            else: 
                report['pkt_ant_%i' % feng_unpkd_pkt['pkt_ant']] += 1
            report['pkt_total'] += 1

if __name__ == '__main__':
    from optparse import OptionParser
    p = OptionParser()
    p.set_usage('%prog [options] CONFIG_FILE')
    p.set_description(__doc__)
    p.add_option('-t', '--man_trigger', dest='man_trigger', action='store_true',
        help='Trigger the snap block manually')   
    p.add_option('-v', '--verbose', dest='verbose', action='store_true',
        help='Print raw output.')  
    p.add_option('-x', '--xaui_port', dest='xaui_port', type='int', default=0,
        help='Capture from which XAUI/10GbE port within the FPGA? Default: 0')
    p.add_option('-s', '--start', dest='startchan', type='int', default=0,
        help='Start capturing from which channel. Default: 0')
    p.add_option('-e', '--end', dest='endchan', type='int', default=0,
        help='Stop capturing at which channel. Default: nchans')
    opts, args = p.parse_args(sys.argv[1:])
    if opts.man_trigger: man_trigger=True
    else: man_trigger=False
    if args==[]:
        config_file=None
    else:
        config_file=args[0]
    verbose=opts.verbose

try:    
    print 'Connecting...',
    c = corr.corr_functions.Correlator(config_file = config_file, log_level = logging.DEBUG if verbose else logging.INFO, connect = False)
    c.connect()
    print 'done'
    binary_point = c.config['feng_fix_pnt_pos']
    packet_len = c.config['10gbe_pkt_len']
    n_chans = c.config['n_chans']
    num_bits = c.config['feng_bits']
    feng_out_type= c.config['feng_out_type']
    if num_bits != 4:
        print 'This script is only written to work with 4 bit quantised values.'
        raise KeyboardInterrupt
    print 'You should have %i XAUI cables connected to each F engine FPGA.' % (c.config['n_xaui_ports_per_ffpga'])
    report = []
    for f in c.ffpgas: report.append(dict())
    spectrum = dict()
    for f, fpga in enumerate(c.ffpgas): spectrum[f] = [numpy.zeros(n_chans), numpy.zeros(n_chans)]
    packets_per_fset = (128 / (64 / 16)) + 1 # (f_values in set / (packet bits / f_value bits)) + one for the header
    snap_depth = pow(2, 8)
    fsets_per_snap = numpy.floor(snap_depth / packets_per_fset)
    bytes_per_fset = packets_per_fset * (128 / 8)
    iterations = int(numpy.ceil(n_chans / fsets_per_snap))
    for i in range(0, iterations):
        offset = int(i * fsets_per_snap * bytes_per_fset)
        print '%i/%i - capturing from offset %i.' % (i, iterations, offset)
        if feng_out_type=='10gbe':
            data = corr.snap.get_gbe_tx_snapshot_feng(c, offset = offset,snap_name = 'snap_gbe_tx%i'%opts.xaui_port)
            #print 'Grabbing and processing the spectrum data from 10GbE TX snap blocks.',
        elif feng_out_typte == 'xaui':
            data = corr.snap.get_xaui_snapsho(c, offset = offset,snap_name = 'snap_gbe_tx%i'%opts.xaui_port)
            #print 'Grabbing and processing the spectrum data from XAUI snap blocks.',
        for d in data:
            process_packets(c, d['fpga_index'], d['data'], spectrum[d['fpga_index']], report[d['fpga_index']])
    #print 'Done.\nGot %i 64-bit packets from %i f-engines.' % (len(data[0]['data']), len(data))
    for f, rep in enumerate(report):
        keys = report[f].keys()
        keys.sort()
        print '------------------------'
        print c.fsrvs[f] 
        print '------------------------'
        for key in sorted(keys):
            print key,': ',report[f][key]
    print '=========================='

    import matplotlib, pylab
    for i in range(0, len(spectrum)):
        ant_str=c.map_input_to_ant(i*2)
        matplotlib.pyplot.figure()
        matplotlib.pyplot.subplot(2, 1, 1)
        matplotlib.pyplot.plot(spectrum[i][0])
        matplotlib.pyplot.title('Antenna %s'%ant_str)

        ant_str=c.map_input_to_ant(i*2+1)
        matplotlib.pyplot.subplot(2, 1, 2)
        matplotlib.pyplot.plot(spectrum[i][1])
        matplotlib.pyplot.title('Antenna %s'%ant_str)
    matplotlib.pyplot.show()

except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()

exit_clean()

