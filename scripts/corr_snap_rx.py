#!/usr/bin/env python

'''
Grabs the contents of "snap_rx0" on the x-engine for analysis.

Rev:
2011-06-29  PVP Port to use new snapshot blocks.
2012-01-09  JRM Only good for one interface per xengine.
'''

import corr, time, numpy, struct, sys, logging

def exit_fail():
    print 'FAILURE DETECTED. Log entries:\n'
    c.log_handler.printMessages()
    print "Unexpected error:", sys.exc_info()
    try:
        c.disconnect_all()
    except: pass
    time.sleep(1)
    raise
    exit()

def exit_clean():
    try:
        c.disconnect_all()
    except: pass
    exit()

def feng_unpack(f, hdr_index, pkt_len):
    sum_polQ_r = 0
    sum_polQ_i = 0
    sum_polI_r = 0
    sum_polI_i = 0

    #average the packet contents from the very first entry
    for pkt_index in range(0, pkt_len):
        pkt_64bit = snap_data[f]['data'][pkt_index].data

        for offset in range(0,64,16):
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
        ave_bits_used_Q_r = numpy.log2(level_polQ_r*(2**num_bits))

    if level_polQ_i < 1.0/(2**num_bits):
        ave_bits_used_Q_i = 0
    else:
        ave_bits_used_Q_i = numpy.log2(level_polQ_i*(2**num_bits))

    if level_polI_r < 1.0/(2**num_bits):
        ave_bits_used_I_r = 0
    else:
        ave_bits_used_I_r = numpy.log2(level_polI_r*(2**num_bits))

    if level_polI_i < 1.0/(2**num_bits):
        ave_bits_used_I_i = 0
    else:
        ave_bits_used_I_i = numpy.log2(level_polI_i*(2**num_bits))

    return {'rms_polQ':rms_polQ,\
            'rms_polI':rms_polI,\
            'ave_bits_used_Q_r':ave_bits_used_Q_r,\
            'ave_bits_used_Q_i':ave_bits_used_Q_i,\
            'ave_bits_used_I_r':ave_bits_used_I_r,\
            'ave_bits_used_I_i':ave_bits_used_I_i}


if __name__ == '__main__':
    from optparse import OptionParser

    p = OptionParser()
    p.set_usage('%prog [options] CONFIG_FILE')
    p.set_description(__doc__)
    p.add_option('-t', '--man_trigger', dest='man_trigger', action='store_true',
        help='Trigger the snap block manually')   
    p.add_option('-v', '--verbose', dest='verbose', action='store_true',
        help='Print raw contents.')  
    p.add_option('-r', '--raw', dest='raw', action='store_true',
        help='Capture clock-for-clock data (ignore external valids on snap block).')
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

    if args==[]:
        config_file=None
    else:
        config_file=args[0]
    verbose=opts.verbose

try:
    print 'Connecting... ',
    c = corr.corr_functions.Correlator(config_file = config_file,log_level = logging.DEBUG if verbose else logging.INFO, connect = False)
    c.connect()
    print 'done.'

    print '------------------------'

    print 'Grabbing and unpacking snap data... ',
    snap_data = corr.snap.get_rx_snapshot(c)
    # returns an array, indexed from zero - but the elements are dictionaries that know their fpga's index
    print 'done.'

    servers = c.xsrvs
    fpgas = c.xfpgas
    binary_point = c.config['feng_fix_pnt_pos']
    num_bits = c.config['feng_bits']
    packet_len = c.config['10gbe_pkt_len']
    n_ants = c.config['n_ants']
    n_chans = c.config['n_chans']
    header_len = 1

    if opts.verbose:
        for s in snap_data:
            for l in range(len(s['data'])):
                print '[%s]' % (servers[s['fpga_index']]),
                print 'IDX: %6i IP: %s. MCNT: %6i. ANT: %4i.  Contents: %016x' % (l, corr.corr_functions.ip2str(s['data'][l].ip_addr), s['data'][l].mcnt, s['data'][l].ant, s['data'][l].data),
                if s['data'][l].valid: print '[VALID]',
                if s['data'][l].flag: print '[FLAG BAD]',
                if s['data'][l].gbe_ack: print '[GBE]',
                if s['data'][l].loop_ack: print '[Loop]',
                if s['data'][l].eof: print '[EOF]',
                print ''
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

        for i in range(len(s['data'])):
            if opts.verbose:
                print ' [%s]' % (servers[s['xfpga_index']]),
                print 'IDX: %6i IP: %s. MCNT: %6i. FREQ: %5i. ANT: %4i.  Contents: %016x' % (i, 
                    corr.corr_functions.ip2str(s['data'][i].ip_addr), 
                    s['data'][i].mcnt, 
                    s['data'][i].mcnt%n_chans,
                    s['data'][i].ant, 
                    s['data'][i].data),
                if s['data'][i].valid: print '[VALID]',
                if s['data'][i].flag: print '[FLAG BAD]',
                if s['data'][i].gbe_ack: print '[GBE]',
                if s['data'][i].loop_ack: print '[Loop]',
                if s['data'][i].eof: print '[EOF!]',
                print ''

            if s['data'][i].eof:
                pkt_ip_str = corr.corr_functions.ip2str(s['data'][i].ip_addr)
                pkt_mcnt = s['data'][i].mcnt
                pkt_ant = s['data'][i].ant
                pkt_freq = pkt_mcnt % n_chans
                hdr_index = prev_eof_index + 1
                pkt_len = i - prev_eof_index

                print '[%s] EOF at %4i. IP: %12s. MCNT: %6i. Freq: %4i ANT: %4i. Len: %3i. ' % (servers[f], i, pkt_ip_str, pkt_mcnt, pkt_freq, pkt_ant, pkt_len),
                if s['data'][hdr_index].gbe_ack: print '[GBE]',
                if s['data'][hdr_index].loop_ack: print '[Loop]',

                report[f]['pkt_total'] += 1

                if prev_eof_index > 0:
                    # Check to make sure the packet length is correct. Don't process if it's bad.
                    if pkt_len != packet_len:
                        print '[BAD PKT LEN]'
                        if not report[f].has_key('bad_pkt_len'):
                            report[f]['bad_pkt_len'] = {'cnt': 1, 'bad_mcnts':[pkt_mcnt]}
                        else:
                            report[f]['bad_pkt_len']['cnt'] += 1
                            report[f]['bad_pkt_len']['bad_mcnts'].append(pkt_mcnt)
                    else:
                        feng_unpkd_pkt = feng_unpack(f, hdr_index, pkt_len)
                        # Check to make sure the hardware unpacker correctly held MCNT constant for the entire packet length:
                        first_mcnt = s['data'][hdr_index].mcnt
                        for pkt_index in range(hdr_index, hdr_index + pkt_len):
                            if first_mcnt != s['data'][pkt_index].mcnt:
                                print '[MCNT ERR]',
                                if not report[f].has_key('mcnt_errors'):
                                    report[f]['mcnt_errors'] = {'cnt':1, 'bad_mcnts':[pkt_mcnt]}
                                else:
                                    report[f]['mcnt_errors']['cnt'] += 1
                                    report[f]['mcnt_errors']['bad_mcnts'].append(pkt_mcnt)

                        try: mcnts[f][pkt_mcnt][pkt_ant] = i
                        except:
                            mcnts[f][pkt_mcnt] = numpy.ones(n_ants, numpy.int) * (-1)
                            mcnts[f][pkt_mcnt][pkt_ant] = i
                        #print mcnts

                        if not report[f].has_key('src_ips'):
                            report[f].update({'src_ips': {pkt_ip_str: 1}})
                        elif report[f]['src_ips'].has_key(pkt_ip_str):
                            report[f]['src_ips'][pkt_ip_str] += 1
                        else:
                            report[f]['src_ips'].update({pkt_ip_str: 1})

                        try: mcnts[f][pkt_mcnt][pkt_ant] = i
                        except:
                            mcnts[f][pkt_mcnt] = numpy.ones(n_ants, numpy.int) * (-1)
                            mcnts[f][pkt_mcnt][pkt_ant] = i
                        #print mcnts

                        print 'HDR @ %4i. 4 bit power: PolQ: %4.2f, PolI: %4.2f' % (hdr_index, feng_unpkd_pkt['rms_polQ'], feng_unpkd_pkt['rms_polI'])

                        if not report[f].has_key('Antenna%02i'%pkt_ant):
                            report[f]['Antenna%02i'%pkt_ant] = 1
                        else:
                            report[f]['Antenna%02i'%pkt_ant] += 1
                else: print 'skipped first packet.'
                prev_eof_index = i

        rcvd_mcnts = mcnts[f].keys()
        rcvd_mcnts.sort()
        if opts.verbose: print '[%s] Received mcnts: ' % servers[f], rcvd_mcnts
        report[f]['min_pkt_latency'] = 9999
        report[f]['max_pkt_latency'] = -1
        for i in rcvd_mcnts[1:-1]:
            max_mcnt = mcnts[f][i].max() / pkt_len
            min_mcnt = mcnts[f][i].min() / pkt_len

            # check to ensure that we received all data for each mcnt:
            if mcnts[f][i].min() < 0:
                if not report[f].has_key('missing_mcnts'):  report[f]['missing_mcnts'] = [i]
                else: report[f]['missing_mcnts'].append(i)
                if opts.verbose:
                    print """[%s] We're missing data for mcnt %016i from antennas """ % (servers[f], i),
                    for ant in range(n_ants):
                        if mcnts[f][i][ant] < 0: print ant,
                    print ''

            # check the latencies in the mcnt values:
            if opts.verbose: print '[%s] MCNT: %i. Max: %i, Min: %i. Diff: %i'%(servers[f],i,max_mcnt,min_mcnt,max_mcnt-min_mcnt)
            if (max_mcnt-min_mcnt)>0:
                if report[f]['max_pkt_latency']<(max_mcnt-min_mcnt) and min_mcnt>0: report[f]['max_pkt_latency']=max_mcnt-min_mcnt
                if report[f]['min_pkt_latency']>(max_mcnt-min_mcnt) and min_mcnt>0: report[f]['min_pkt_latency']=max_mcnt-min_mcnt

    print '\n\nDone with all servers.\nSummary:\n=========================='
    for k, r in report.iteritems():
        keys = report[k].keys()
        keys.sort()
        srvr = servers[r['fpga_index']]
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

