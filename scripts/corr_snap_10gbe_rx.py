#!/usr/bin/env python

'''
Grabs the contents of "snap_gbe_rx" for analysis.
Assumes the correlator is already initialsed and running etc.

Author: Jason Manley

Revs:
2010-07-23: JRM Ported for cor-0.5.5
                Added option to capture from core other than 0.
2011-06-30: PVP Updated to use new snapshot blocks and snap class.

'''
import corr, time, numpy, struct, sys, logging

def exit_fail():
    print 'FAILURE DETECTED. Log entries:\n',c.log_handler.printMessages()
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

def unpack(f, hdr_index, pkt_len):
    hdr_64bit = snap_data[f]['data'][hdr_index].data
    pkt_mcnt = hdr_64bit >> 16
    pkt_ant = hdr_64bit & ((2**16) - 1)
    pkt_freq = pkt_mcnt % c.config['n_chans']
    pkt_xeng = pkt_freq / (c.config['n_chans'] / c.config['n_xeng'])

    sum_polQ_r = 0
    sum_polQ_i = 0
    sum_polI_r = 0
    sum_polI_i = 0

    # average the packet contents - ignore first entry (header)
    for pkt_index in range(1, pkt_len):
        pkt_64bit = snap_data[f]['data'][hdr_index + pkt_index].data
        for offset in range(0, 64, 16):
            polQ_r = (pkt_64bit & ((2**(offset+16)) - (2**(offset+12))))>>(offset+12)
            polQ_i = (pkt_64bit & ((2**(offset+12)) - (2**(offset+8))))>>(offset+8)
            polI_r = (pkt_64bit & ((2**(offset+8)) - (2**(offset+4))))>>(offset+4)
            polI_i = (pkt_64bit & ((2**(offset+4)) - (2**(offset))))>>offset
            #square each number and then sum it
            sum_polQ_r += (float(((numpy.int8(polQ_r << 4)>> 4)))/(2**binary_point))**2
            sum_polQ_i += (float(((numpy.int8(polQ_i << 4)>> 4)))/(2**binary_point))**2
            sum_polI_r += (float(((numpy.int8(polI_r << 4)>> 4)))/(2**binary_point))**2
            sum_polI_i += (float(((numpy.int8(polI_i << 4)>> 4)))/(2**binary_point))**2

    num_accs = (pkt_len-1)*(64/16)

    level_polQ_r = numpy.sqrt(float(sum_polQ_r)/ num_accs)
    level_polQ_i = numpy.sqrt(float(sum_polQ_i)/ num_accs)
    level_polI_r = numpy.sqrt(float(sum_polI_r)/ num_accs)
    level_polI_i = numpy.sqrt(float(sum_polI_i)/ num_accs)

    rms_polQ = numpy.sqrt(((level_polQ_r)**2)  +  ((level_polQ_i)**2))
    rms_polI = numpy.sqrt(((level_polI_r)**2)  +  ((level_polI_i)**2))

    if level_polQ_r < 1.0/(2**num_bits):
        ave_bits_used_Q_r = 0
    else:
        ave_bits_used_Q_r = numpy.log2(level_polQ_r*(2**binary_point))

    if level_polQ_i < 1.0/(2**num_bits):
        ave_bits_used_Q_i = 0
    else:
        ave_bits_used_Q_i = numpy.log2(level_polQ_i*(2**binary_point))

    if level_polI_r < 1.0/(2**num_bits):
        ave_bits_used_I_r = 0
    else:
        ave_bits_used_I_r = numpy.log2(level_polI_r*(2**binary_point))

    if level_polI_i < 1.0/(2**num_bits):
        ave_bits_used_I_i = 0
    else:
        ave_bits_used_I_i = numpy.log2(level_polI_i*(2**binary_point))

    return {'pkt_mcnt': pkt_mcnt,\
            'pkt_ant':  pkt_ant,\
            'pkt_freq': pkt_freq,\
            'pkt_xeng': pkt_xeng,\
            'rms_polQ': rms_polQ,\
            'rms_polI': rms_polI,\
            'ave_bits_used_Q_r':    ave_bits_used_Q_r,\
            'ave_bits_used_Q_i':    ave_bits_used_Q_i,\
            'ave_bits_used_I_r':    ave_bits_used_I_r,\
            'ave_bits_used_I_i':    ave_bits_used_I_i}

if __name__ == '__main__':
    from optparse import OptionParser

    p = OptionParser()
    p.set_usage('%prog [options] CONFIG_FILE')
    p.set_description(__doc__)
    p.add_option('-r', '--raw', dest='raw', action='store_true',
        help='Capture clock-for-clock data (ignore external valids on snap block).')   
    p.add_option('-t', '--man_trigger', dest='man_trigger', action='store_true',
        help='Trigger the snap block manually')   
    p.add_option('-v', '--verbose', dest='verbose', action='store_true',
        help='Be Verbose; print raw packet contents.')   
    p.add_option('-n', '--core_n', dest='core_n', type='int', default=0,
        help='Core number to decode. Default 0.')
    opts, args = p.parse_args(sys.argv[1:])
    if opts.man_trigger:
        man_trig=True
    else:
        man_trig=False

    if opts.raw:
        man_valid=True
    else:
        man_valid=False
    if opts.man_trigger:
        man_ctrl = (1<<1)+1
    else:        
        man_ctrl = 1
    if opts.raw:
        man_ctrl += (1<<2)

    if args == []:
        config_file = None
    else:
        config_file = args[0]
    verbose = opts.verbose

try:    
    print 'Connecting...',
    c = corr.corr_functions.Correlator(config_file = config_file, log_level = logging.DEBUG if verbose else logging.INFO, connect = False)
    c.connect()
    print 'done'

    print '------------------------'

    print 'Grabbing and unpacking snap data... ',
    snap_data = corr.snap.get_gbe_rx_snapshot(c)
    print 'done.'

    binary_point = c.config['feng_fix_pnt_pos']
    num_bits = c.config['feng_bits']
    packet_len = c.config['10gbe_pkt_len']
    n_ants = c.config['n_ants']
    n_ants_per_xaui = c.config['n_ants_per_xaui']

    # figure out which antennas are connected to this X engine via XAUI so that we can ignore the lack of any packets from these antennas...
    base_ants = []

    #base_ants = [[x for x in range(c.config['n_xaui_ports_per_xfpga'])] for f in c.xfpgas]
    #x_with_connected_cables = n_ants / n_ants_per_xaui / c.config['n_xaui_ports_per_xfpga']
    #ant = 0
    #for x in range(c.config['n_xaui_ports_per_xfpga']):
    #    for f in range(x_with_connected_cables):
    #        base_ants[f][x] = ant
    #        ant += n_ants_per_xaui

    report = dict()
    mcnts = dict()
    print 'Analysing packets:'
    for s in snap_data:
        f = s['fpga_index']        
        report[f] = dict()
        mcnts[f] = dict()
        report[f]['pkt_total'] = 0
        pkt_len = 0
        prev_eof_index = -1
        report[f]['fpga_index'] = f
        fpga = c.xfpgas[f]

        for i in range(len(s['data'])):
            if opts.verbose or opts.raw:
                pkt_64bit = snap_data[f]['data'][i].data
                print '[%s] IDX: %4i Contents: %016x' % (c.xsrvs[f], i, pkt_64bit),
                if s['data'][i].led_rx: print '[rx_data]',
                if s['data'][i].valid: print '[valid]',
                if s['data'][i].ack: print '[rd_ack]',
                if not s['data'][i].led_up: print '[LNK DN]',
                if s['data'][i].bad_frame: print '[BAD FRAME]',
                if s['data'][i].overflow: print '[OVERFLOW]',
                if s['data'][i].eof: print '[eof]',
                print ''

            if s['data'][i].eof and not opts.raw:
                pkt_ip_str = corr.corr_functions.ip2str(s['data'][i].ip_addr)
                print '[%s] EOF at %4i. Src: %12s. Len: %3i. ' % (c.xsrvs[f], i, pkt_ip_str, i - prev_eof_index),
                report[f]['pkt_total'] += 1
                hdr_index = prev_eof_index + 1
                pkt_len = i - prev_eof_index
                prev_eof_index = i

                if not report[f].has_key('dest_ips'):
                    report[f].update({'dest_ips': {pkt_ip_str: 1}})
                elif report[f]['dest_ips'].has_key(pkt_ip_str):
                    report[f]['dest_ips'][pkt_ip_str] += 1
                else:
                    report[f]['dest_ips'].update({pkt_ip_str: 1})

                if pkt_len != packet_len + 1:
                    print '[BAD PKT LEN]'
                    if not report[f].has_key('bad_pkt_len'):
                        report[f]['bad_pkt_len'] = 1
                    else:
                        report[f]['bad_pkt_len'] += 1
                else:
                    unpkd_pkt = unpack(f, hdr_index, pkt_len)
                    
                    # Record the reception of the packet for this antenna, with this mcnt
                    try: mcnts[f][unpkd_pkt['pkt_mcnt']][unpkd_pkt['pkt_ant']] = i
                    except: 
                        mcnts[f][unpkd_pkt['pkt_mcnt']] = numpy.ones(n_ants,numpy.int) * (-1)
                        mcnts[f][unpkd_pkt['pkt_mcnt']][unpkd_pkt['pkt_ant']] = i
                    #print mcnts

                    print 'HDR @ %4i. MCNT %12u. Ant: %3i. Freq: %4i. Xeng: %2i, 4 bit power: PolQ: %4.2f, PolI: %4.2f' % (hdr_index, unpkd_pkt['pkt_mcnt'], unpkd_pkt['pkt_ant'], unpkd_pkt['pkt_freq'], unpkd_pkt['pkt_xeng'], unpkd_pkt['rms_polQ'], unpkd_pkt['rms_polI'])

                    if not report[f].has_key('Antenna%i' % unpkd_pkt['pkt_ant']):
                        report[f]['Antenna%i' % unpkd_pkt['pkt_ant']] = 1
                    else:
                        report[f]['Antenna%i' % unpkd_pkt['pkt_ant']] += 1

        rcvd_mcnts = mcnts[f].keys()
        rcvd_mcnts.sort()

        if opts.verbose: print '[%s] Received mcnts: ' % c.xsrvs[f], rcvd_mcnts
        report[f]['min_pkt_latency'] = 99999999
        report[f]['max_pkt_latency'] = -1

        for mcnt in rcvd_mcnts[2: -2]:
            if c.config['feng_out_type'] == 'xaui':
                # simulate the reception of the loopback antenna's mcnts, but only for the x engines that actually have connected f engines:
                if f < x_with_connected_cables:
                    print 'Replacing antennas on FPGA %s for mcnt %i' % (c.xsrvs[f], mcnt)
                    for a in range(base_ants[f][opts.core_n],base_ants[f][opts.core_n] + c.config['n_ants_per_xaui']):
                        mcnts[f][mcnt][a] = mcnts[f][mcnt].max()

            # find the min and max indices of each mcnt:
            max_mcnt = mcnts[f][mcnt].max() / pkt_len
            min_mcnt = mcnts[f][mcnt].min() / pkt_len

            # check to ensure that we received all data for each mcnt, by looking for any indices that weren't recorded:
            if mcnts[f][mcnt].min() < 0:
                if not report[f].has_key('missing_mcnts'):  report[f]['missing_mcnts'] = [mcnt]
                else: report[f]['missing_mcnts'].append(mcnt)
                if opts.verbose:
                    print """[%s] We're missing data for mcnt %016i from antennas """ % (c.xsrvs[f], mcnt),
                    for ant in range(n_ants):
                        if mcnts[f][mcnt][ant] < 0: print ant,
                    print ''

            # check the latencies in the mcnt values:
            if opts.verbose: print '[%s] MCNT: %i. Max: %i, Min: %i. Diff: %i' % (c.xsrvs[f], mcnt, max_mcnt, min_mcnt, max_mcnt - min_mcnt)
            if (max_mcnt - min_mcnt) > 0:
                if report[f]['max_pkt_latency'] < (max_mcnt - min_mcnt) and min_mcnt >= 0: report[f]['max_pkt_latency'] = max_mcnt - min_mcnt
                if report[f]['min_pkt_latency'] > (max_mcnt - min_mcnt) and min_mcnt >= 0: report[f]['min_pkt_latency'] = max_mcnt - min_mcnt

    print '\n\nDone with all servers.\nSummary:\n=========================='
    for k, r in report.iteritems():
        keys = report[k].keys()
        keys.sort()
        srvr = c.xsrvs[r['fpga_index']]
        print '------------------------'
        print srvr
        print '------------------------'
        for key in keys:
            print key,': ', r[key]
    print '=========================='

except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()

exit_clean()

# end
