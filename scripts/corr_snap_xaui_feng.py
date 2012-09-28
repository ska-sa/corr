#!/usr/bin/env python

'''Grabs the contents of "snap_xaui" on the F engines for analysis.
Assumes 4 bit values for power calculations.
Assumes the correlator is already initialsed and running etc.
\n
Author: Jason Manley
\n
Revisions:\n
2010-07-22: JRM Copied from corr_snap_xaui.py\n
2011-09-09: PVP Updated for new snapshot blocks.
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

def tvg_check(fsrv, count, d, freq):
    if not d.hdr_valid:
        data_chan = d.data & 0xffffffff
        if data_chan != freq:
            #raise RuntimeError("[%s] header says freq %d, tvg data has %d instead." % (fsrv, freq, data_chan))
            print "ERROR: [%s] header says freq %d, tvg data has %d instead." % (fsrv, freq, data_chan)

def print_packet_info_basic(server, count, d):
    print '[%s @ %4i]: %016X' % (server, count, d.data),
    if d.eof: print '[EOF]',
    if d.link_down: print '[LINK DOWN]',
    if d.mrst: print '[MRST]',
    if d.sync: print '[SYNC]',
    if d.hdr_valid: print '[HDR]',
    print ''

def print_packet_info(server, header_index, length, unpacked, chans):
    print '[%s] [Pkt@ %4i Len: %2i] pcnt_curr(%10i) MCNT(%10i) ANT(%1i) Freq(%4i) Tstamp(%10i) RMS: X: %1.2f Y: %1.2f. {X: %1.2f+%1.2fj (%2.1f & %2.1f bits), Y:%1.2f+%1.2fj (%2.1f & %2.1f bits)} {Pk: X,Y: %1.2f,%1.2f (%2.1f,%2.1f bits)}' % \
        (server,\
        header_index,\
        length,\
        pcnt_current,\
        unpacked['pkt_mcnt'],\
        unpacked['pkt_ant'],\
        unpacked['pkt_pcnt'],\
        unpacked['pkt_timestamp'],\
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
    pkt_mcnt = pkt_64bit >> 16
    pkt_ant  = pkt_64bit & ((2**16)-1)
    pkt_timestamp = pkt_mcnt >> chan_bits
    pkt_pcnt = pkt_mcnt & (n_chans-1)
    pkt_freq = pkt_pcnt
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
        #pkt_64bit = struct.unpack('>Q',bram_dmp['bram_msb'][f][(4*abs_index):(4*abs_index)+4]+bram_dmp['bram_lsb'][f][(4*abs_index):(4*abs_index)+4])[0]
        pkt_64bit = data[f]['data'][abs_index].data
        raw_data.append(pkt_64bit)
        for offset in range(0, 64, 16):
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
            'pkt_timestamp':pkt_timestamp,\
            'pkt_pcnt':pkt_pcnt,\
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

if __name__ == '__main__':
    from optparse import OptionParser
    p = OptionParser()
    p.set_usage('%prog [options] CONFIG_FILE')
    p.set_description(__doc__)
    p.add_option('-t', '--man_trigger', dest='man_trigger', action='store_true', default = False,
        help='Trigger the snap block manually')   
    p.add_option('-e', '--man_valid', dest='man_valid', action='store_true', default = False,
        help='Apply manual valid to the snap write enable.')   
    p.add_option('-v', '--verbose', dest='verbose', action='store_true', default = False,
        help='Print raw output.')  
    p.add_option('', '--tvg_check', dest='tvg', action='store_true', default = False,
        help='Enable the packetiser TVG and check the packet and channel info in the tvg data against the header info.')  
    p.add_option('-o', '--offset', dest='offset', type='int', default=0,
        help='Offset in CHANNELS stored in the XAUI snap block whence we shall start capturing. Default: 0')
    p.add_option('-x', '--xaui_port', dest='xaui_port', type='int', default=0,
        help='Capture from which XAUI port. Default: 0')
    opts, args = p.parse_args(sys.argv[1:])
    dev_name = 'snap_xaui%i'%opts.xaui_port
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
    report = []

#Even with no XAUI links, might still have the snap block in the feng
#    if c.config['feng_out_type'] != 'xaui':
#        print 'Your system does not have any XAUI links!'
#        raise KeyboardInterrupt

    binary_point = c.config['feng_fix_pnt_pos']
    packet_len = c.config['10gbe_pkt_len']
    n_chans = c.config['n_chans']
    chan_bits = int(numpy.log2(n_chans))
    num_bits = c.config['feng_bits']

    if num_bits != 4:
        print 'This script is only written to work with 4 bit quantised values.'
        raise KeyboardInterrupt
    
    print 'You should have %i XAUI cables connected to each F engine FPGA.' % (c.config['n_xaui_ports_per_ffpga'])

    if opts.tvg:
        print "Enabling packetiser TVG..."
        if c.is_narrowband():
            corr.corr_functions.write_masked_register(c.ffpgas, corr.corr_nb.register_fengine_control, tvg_en = True,  tvgsel_pkt = True)
            corr.corr_functions.write_masked_register(c.ffpgas, corr.corr_nb.register_fengine_control, tvg_en = False, tvgsel_pkt = True)
        elif c.is_wideband():
            raise RuntimeError('No TVG in wideband yet.')
        else:
            raise RuntimeError('Unknown mode.')

    # 33 = one 64-bit packet in 128-bit snap, 4 16-bit (2 pols, 4.3r+i each) values in each packet. So 128-deep collections of f-channels take 32 packets. Plus one header packet.
    # (128 / 8) = size of 128-bit snap block word in bytes
    # The offset is in bytes, but must work on packets, because the 128-bit words each contain a packet and the fchan sets take a certain number of packets.
    packets_per_f_chan_group = 128 / (64 / 16)
    offset = opts.offset * (packets_per_f_chan_group + 1) * (128 / 8)
    print 'Grabbing data off snap blocks with offset %i channels (%i bytes) and unpacking it...' % (opts.offset, offset),
    #for x in range(c.config['n_xaui_ports_per_ffpga']):
    #bram_dmp = c.fsnap_all(dev_name,brams,man_trig=man_trigger,wait_period=3,offset=opts.offset*num_bits*2*2/64*packet_len)
    data = corr.snap.get_xaui_snapshot(c, offset = offset, man_trigger = opts.man_trigger, man_valid = opts.man_valid)
    print 'done.'

    # read peecount
    msw = c.ffpgas[0].read_uint('mcount_msw')
    lsw = c.ffpgas[0].read_uint('mcount_lsw')
    mcount = (msw << 32) + lsw
    pcnt_current = int(((msw << 32) + lsw) * c.config['pcnt_scale_factor'] / c.config['mcnt_scale_factor'])

    print 'pcnt_sf(%i) mcnt_sf(%i) mcount(%i) pcnt_current(%i)' % (c.config['pcnt_scale_factor'], c.config['mcnt_scale_factor'], mcount, pcnt_current)

    print 'Analysing packets...'
    skip_indices = []
    #data = [data[0]]
    for fengine_data in data:
        f = fengine_data['fpga_index']
        fsrv = c.fsrvs[f]
        print fsrv + ': '
        report.append(dict())
        report[f]['pkt_total'] = 0
        pkt_hdr_idx = -1
        pkt_hdr_current_freq = -1
        for i, d in enumerate(fengine_data['data']):
            if opts.tvg:
                tvg_check(fsrv, i, d, pkt_hdr_current_freq)
            if opts.verbose:
                print_packet_info_basic(fsrv, i, d)
            if d.link_down:
                print '[%s] LINK DOWN AT %i' % (fsrv, i)
            elif d.hdr_valid:
                pkt_mcnt = (d.data & ((2**64)-(2**16)))>>16
                pkt_hdr_current_freq = pkt_mcnt % n_chans
                pkt_hdr_idx = i
                # skip_indices records positions in table which are ADC updates and should not be counted towards standard data.
                skip_indices = []
                #print ('HEADER RECEIVED @ %i with freq %i' % (i, pkt_hdr_current_freq))
#            elif bram_oob[f]['adc'][i]:
#                print "Got a legacy ADC amplitude update. This shouldn't happen in modern designs. I think you connected an old (or a faulty!) F engine."
#                skip_indices.append(i)
            elif d.eof:
                # skip the first packet entry which has no header (snap block triggered on sync)
                if pkt_hdr_idx < 0:
                    print "Skipping data at f(%i) i(%i) hdr_index(%i)" % (f, i, pkt_hdr_idx)
                    continue
                pkt_len = i - pkt_hdr_idx + 1
                feng_unpkd_pkt = feng_unpack(f, pkt_hdr_idx, pkt_len, skip_indices)
                #print feng_unpkd_pkt['raw_packets']
                print_packet_info(server = fsrv, header_index = pkt_hdr_idx, length = pkt_len - len(skip_indices), unpacked = feng_unpkd_pkt, chans = n_chans)
                if opts.verbose: print ''
                # packet_len is length of data, not including header
                if pkt_len - len(skip_indices) != (packet_len + 1):
                    print 'MALFORMED PACKET! of length %i starting at index %i' % (pkt_len - len(skip_indices), i)
                    print 'len of skip_indices: %i:' % len(skip_indices), skip_indices
                    if not report[f].has_key('Malformed packets'):
                        report[f]['Malformed packets'] = 1
                    else: 
                        report[f]['Malformed packets'] += 1

                if not report[f].has_key('pkt_ant_%i'%feng_unpkd_pkt['pkt_ant']):
                    report[f]['pkt_ant_%i' % feng_unpkd_pkt['pkt_ant']] = 1
                else: 
                    report[f]['pkt_ant_%i' % feng_unpkd_pkt['pkt_ant']] += 1
                report[f]['pkt_total'] += 1

    print '\n\nDone with all servers.\nSummary:\n==========================' 
    for f,srv in enumerate(c.fsrvs):
        keys = report[f].keys()
        keys.sort()
        print '------------------------'
        print c.fsrvs[f] 
        print '------------------------'
        for key in sorted(keys):
            print key,': ',report[f][key]
    print '=========================='

except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()

exit_clean()

