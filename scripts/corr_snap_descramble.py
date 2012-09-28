#!/usr/bin/env python

'''
Grabs the contents of "snap_descramble" for analysis. Valid for rev333 and onwards only. This has no OOB capturing. Grabs an entire spectrum by default.

Author: Jason Manley

Rev:
2011-06-27  JRM Port to new snapshot blocks
2010-07-29  JRM Port to corr-0.5.0
                Added more useful summary logging.

'''
import corr, time, numpy, struct, sys, logging, construct
from construct import *

# OOB signalling bit offsets - seem to be the same for wb and nb:
data_bitstruct = construct.BitStruct("oob",
    BitField("data", 16),
    BitField("mcnt", 13),
    Flag("valid"),
    Flag("flag"),
    Flag("received"))
data_repeater = construct.GreedyRepeater(data_bitstruct)

dev_prefix = 'snap_descramble'

def exit_fail():
    print 'FAILURE DETECTED. Log entries:\n', c.log_handler.printMessages()
    print "Unexpected error:", sys.exc_info()
    try:
        c.disconnect_all()
    except:
        pass
    if verbose:
        raise
    exit()

def exit_clean():
    try:
        c.disconnect_all()
    except:
        pass
    exit()

def xeng_in_unpack(oob, start_index):
    sum_polQ_r = 0
    sum_polQ_i = 0
    sum_polI_r = 0
    sum_polI_i = 0
    rcvd_errs = 0
    flag_errs = 0
    #average the packet contents from the very first entry
    for slice_index in range(c.config['xeng_acc_len']):
        abs_index = start_index + slice_index
        polQ_r = (oob[abs_index]['data'] & ((2**(16)) - (2**(12))))>>(12)
        polQ_i = (oob[abs_index]['data'] & ((2**(12)) - (2**(8))))>>(8)
        polI_r = (oob[abs_index]['data'] & ((2**(8)) - (2**(4))))>>(4)
        polI_i = (oob[abs_index]['data'] & ((2**(4)) - (2**(0))))>>0

        #square each number and then sum it
        sum_polQ_r += (float(((numpy.int8(polQ_r << 4)>> 4)))/(2**binary_point))**2
        sum_polQ_i += (float(((numpy.int8(polQ_i << 4)>> 4)))/(2**binary_point))**2
        sum_polI_r += (float(((numpy.int8(polI_r << 4)>> 4)))/(2**binary_point))**2
        sum_polI_i += (float(((numpy.int8(polI_i << 4)>> 4)))/(2**binary_point))**2

        if not oob[abs_index]['received']: rcvd_errs += 1
        if oob[abs_index]['flag']: flag_errs += 1

    num_accs = c.config['xeng_acc_len']

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

    return {'rms_polQ':rms_polQ,\
            'rms_polI':rms_polI,\
            'rcvd_errs':rcvd_errs,\
            'flag_errs':flag_errs,\
            'ave_bits_used_Q_r':ave_bits_used_Q_r,\
            'ave_bits_used_Q_i':ave_bits_used_Q_i,\
            'ave_bits_used_I_r':ave_bits_used_I_r,\
            'ave_bits_used_I_i':ave_bits_used_I_i}

def grab_snap_data(c, dev_name):
    """
    Grab the required amount of data off the snap blocks on the x-engines.
    """
    dmp = dict()
    print 'Trying to retrieve %i words from %s for each x-engine...' % (expected_length, dev_name)
    print '------------------------'
    #dmp = [[0 for i in range(expected_length*4)] for f in fpgas]
    print 'Triggering and capturing from offset 0 ...',
    dmp = corr.snap.snapshots_get(c.xfpgas, dev_name, man_trig = man_trigger, man_valid = raw_capture, wait_period = 2, offset = 0, circular_capture = False)
    print 'done'
    while (dmp['lengths'][0] / 4) < expected_length:
        capture_offset = dmp['lengths'][0]
        print 'Triggering and capturing at offset %i...' % capture_offset,
        bram_tmp = corr.snap.snapshots_get(c.xfpgas, dev_name, man_trig = man_trigger, man_valid = raw_capture, wait_period = 1, offset = capture_offset, circular_capture = False)
        for f, fpga in enumerate(c.xfpgas):
            dmp['data'][f] += bram_tmp['data'][f]
        print 'done'
        for f, fpga in enumerate(c.xfpgas):
            if (bram_tmp['lengths'][f] != bram_tmp['lengths'][f - 1]):
                raise RuntimeError('Not all X engines captured the same amount of snapshot data.')
            dmp['lengths'][f] += bram_tmp['lengths'][f]
        time.sleep(0.1)
    for f, fpga in enumerate(c.xfpgas):
        dmp['data'][f] = ''.join(dmp['data'][f])
    #print 'BRAM DUMPS:'
    #print dmp
    for f, fpga in enumerate(c.xfpgas):
        print 'Got %i bytes starting at offset %i from snapshot %s on device %s' % (dmp['lengths'][f], dmp['offsets'][f], dev_name, c.xsrvs[f])
    #print 'Total size for each x engine: %i bytes'%len(dmp[0])
    return dmp

def create_data(c, xeng_number):
    
    # get the data
    dev_name = '%s%1i' % (dev_prefix, xeng_number)
    snapdump = grab_snap_data(c, dev_name)

    print 'Unpacking bram contents...',
    sys.stdout.flush()
    oobdata = dict()
    for f, fpga in enumerate(c.xfpgas):
        if snapdump['lengths'][f] == 0:
            print 'Warning: got nothing back from snap block %s on %s.' % (dev_name, c.xsrvs[f])
        else:
            oobdata[f] = data_repeater.parse(snapdump['data'][f])
    print 'done.'

    if opts.verbose:
        for f, fpga in enumerate(c.xfpgas):
            i = snapdump['offsets'][f]
            for ir, oob in enumerate(oobdata[f]):
                pkt_mcnt = oob['mcnt']
                pkt_data = oob['data']
                exp_ant = (i / c.config['xeng_acc_len']) % c.config['n_ants']
                xeng = (c.config['x_per_fpga'])*f + xeng_number
                if c.config['xeng_format'] == 'inter': 
                    exp_mcnt = ((i/c.config['xeng_acc_len'])/c.config['n_ants'])*c.config['n_xeng'] + xeng
                else:
                    exp_mcnt = ((i/c.config['xeng_acc_len'])/c.config['n_ants'])+ xeng*(c.config['n_chans']/c.config['n_xeng'])
                exp_freq = (exp_mcnt) % c.config['n_chans']
                act_mcnt = (pkt_mcnt+xeng)
                act_freq = act_mcnt%c.config['n_chans']
                xeng_slice = i % c.config['xeng_acc_len']+1
                print '[%s] Xeng%i BRAM IDX: %6i Valid IDX: %10i Rounded MCNT: %6i. Global MCNT: %6i. Freq %4i, Data: 0x%04x. EXPECTING: slice %3i/%3i of ant %3i, freq %3i.' % (fpga.host, \
                        xeng, ir, i, pkt_mcnt, act_mcnt, act_freq, pkt_data, xeng_slice, c.config['xeng_acc_len'], exp_ant, exp_freq),
                if oob['valid']: 
                    print '[VALID]',
                    i = i + 1
                if oob['received']:  print '[RCVD]',
                if oob['flag']:      print '[FLAG_BAD]',
                print ''

    #print len(dmp['data'][0])
    #print dmp['lengths']

    if not raw_capture and not opts.circ:
        print 'Analysing contents of %s...' % dev_name
        rep = dict()
        mcnts = dict()
        freqs = []
        last_freq = -1
        if opts.plot:
            import numpy
            plot_data = []
            for i in range(0, c.config['n_ants']):
                plot_data.append([numpy.zeros(c.config['n_chans']), numpy.zeros(c.config['n_chans'])])
        else:
            plot_data = None
        for f, fpga in enumerate(c.xfpgas):
            rep[f] = dict()
            for i in range(0, snapdump['lengths'][f] / 4, c.config['xeng_acc_len']):        
                pkt_mcnt = oobdata[f][i]['mcnt']
                pkt_data = oobdata[f][i]['data']
                exp_ant = (i / c.config['xeng_acc_len']) % c.config['n_ants']
                xeng = (c.config['x_per_fpga']) * f + xeng_number
                if c.config['xeng_format'] == 'inter': 
                    exp_mcnt = ((i/c.config['xeng_acc_len'])/c.config['n_ants'])*c.config['n_xeng'] + xeng
                    exp_freq = (i/c.config['xeng_acc_len'])/c.config['n_ants'] * c.config['n_xeng'] + ((c.config['x_per_fpga']) * f + xeng_number)
                else:
                    exp_mcnt = ((i/c.config['xeng_acc_len'])/c.config['n_ants'])+ xeng*(c.config['n_chans']/c.config['n_xeng'])
                    exp_freq = (exp_mcnt) % c.config['n_chans']
                xeng_unpkd = xeng_in_unpack(oobdata[f], i)
                if not freqs.__contains__(exp_freq):
                    if exp_freq != last_freq + 1:
                        print 'Frequency jumped from %d to %d' % (last_freq, exp_freq)
                    freqs.append(exp_freq)
                    last_freq = exp_freq
                if opts.plot:
                    plot_data[exp_ant][0][exp_freq] = plot_data[exp_ant][0][exp_freq] + xeng_unpkd['rms_polQ']
                    plot_data[exp_ant][1][exp_freq] = plot_data[exp_ant][1][exp_freq] + xeng_unpkd['rms_polI']
                print '[%s] IDX: %6i. XENG: %3i. ANT: %4i. FREQ: %4i. 4 bit power: PolQ: %4.2f, PolI: %4.2f' % (fpga.host, i, xeng, exp_ant, exp_freq, xeng_unpkd['rms_polQ'], xeng_unpkd['rms_polI']),
                if xeng_unpkd['rcvd_errs'] > 0: 
                    print '[%i RCV ERRS!]'%xeng_unpkd['rcvd_errs'],
                    if not rep[f].has_key('Rcv Errors'):
                        rep[f]['Rcv Errors ant %i'%exp_ant] = 1
                    else:
                        rep[f]['Rcv Errors ant %i'%exp_ant] += 1
                if xeng_unpkd['flag_errs'] > 0: 
                    print '[%i FLAGGED DATA]'%xeng_unpkd['flag_errs'],
                    if not rep[f].has_key('Flagged bad data ant %i'%exp_ant):
                        rep[f]['Flagged bad data ant %i'%exp_ant] = 1
                    else:
                        rep[f]['Flagged bad data ant %i'%exp_ant] += 1
                if xeng_unpkd['flag_errs']==0 and xeng_unpkd['rcvd_errs']==0: 
                    if not rep[f].has_key('Good data received ant %i'%exp_ant):
                        rep[f]['Good data received ant %i'%exp_ant] = 1
                    else:
                        rep[f]['Good data received ant %i'%exp_ant] += 1
                if not rep[f].has_key('Total data received'):
                    rep[f]['Total data received'] = 1
                else:
                    rep[f]['Total data received'] += 1
                print ''

    return snapdump, oobdata, rep, plot_data

if __name__ == '__main__':
    from optparse import OptionParser

    p = OptionParser()
    p.set_usage('%prog [options] CONFIG_FILE')
    p.set_description(__doc__)
    p.add_option('-n', '--n_chans', dest='n_chans', type='int', default=0,
        help='How many channels should we retrieve?')   
    p.add_option('-v', '--verbose', dest='verbose', action='store_true',
        help='Print raw contents.')   
    p.add_option('-r', '--raw', dest='raw', action='store_true',
        help='Capture raw data (as opposed to only valid data).')   
    p.add_option('-t', '--trigger', dest='man_trigger', action='store_true',
        help='Trigger snap block manually.')   
    p.add_option('-c', '--circ', dest='circ', action='store_true',
        help='Enable circular buffering, waiting for error in datastream before capturing.')   
    p.add_option('-o', '--core_n', dest='core_n', type='int', default=0,
        help='Core number to decode. Default 0. 2 means both (this can take a while).')
    p.add_option('-p', '--plot', dest='plot', action='store_true', default=False,
        help='Plot the data per antenna, each pol.')

    opts, args = p.parse_args(sys.argv[1:])

    if opts.man_trigger:
        man_trigger = True
        print 'NOTE: expected frequencies and antenna indices will be wrong with manual trigger option.'
    else:
        man_trigger = False

    if opts.raw:
        raw_capture = True
        print 'NOTE: number of decoded frequency channels will not be accurate with RAW capture mode.'
    else:
        raw_capture = False

    if opts.core_n == 0:
        xeng_numbers = [0]
    elif opts.core_n == 1:
        xeng_numbers = [0]
    elif opts.core_n == 2:      
        xeng_numbers = [0, 1]
    else:
        raise RuntimeError('Unsupported core number selection.') 
 
    desired_n_chans = opts.n_chans

    if args == []:
        config_file=None
    else:
        config_file=args[0]
    verbose = opts.verbose

try:
    print 'Connecting...',
    c = corr.corr_functions.Correlator(config_file = config_file, log_level = logging.DEBUG if verbose else logging.INFO, connect = False)
    c.connect()
    print 'done'

    binary_point = c.config['feng_fix_pnt_pos']
    num_bits = c.config['feng_bits']
    if desired_n_chans == 0:
        desired_n_chans = c.config['n_chans']
    expected_length = desired_n_chans / c.config['n_xeng'] * c.config['n_ants'] * c.config['xeng_acc_len']

    if opts.circ:
        bram_dmp = dict()
        for xeng_number in xeng_numbers:
            print 'Enabling circular-buffer capture on snap block %s.\n Triggering and Capturing, waiting for error...' % dev_name,
            sys.stdout.flush()
            bram_dmp[dev_name] = corr.snap.snapshots_get(c.xfpgas, '%s%1i' % (dev_prefix, xeng_number), man_trig = man_trigger, man_valid = raw_capture, wait_period = -1, offset = 0, circular_capture = True)
            print 'done.'
    else:
        bram_dmp = dict()
        bram_oob = dict()
        report = dict()
        plot_data = dict()
        # get x-engine data off all xfpgas, for x-engine 0, 1, ...
        for xeng_number in xeng_numbers:
            bram_dmp[xeng_number], bram_oob[xeng_number], report[xeng_number], plot_data[xeng_number] = create_data(c, xeng_number)
        print '\n\nDone with all xFPGAs.\nSummary:\n=========================='
        for f, fpga in enumerate(c.xfpgas):
            for x, xeng_number in enumerate(xeng_numbers):
                print '------------------------'
                print fpga.host, '%s%1i' % (dev_prefix, xeng_number)
                print '------------------------'
                for key in sorted(report[x][f].iteritems()):
                    print key[0], ': ', key[1]
        print '=========================='

        if opts.plot:
            pd = []
            # rebuild sensible spectra
            if opts.core_n == 2:
                for ctr, a in enumerate(plot_data[0]):
                    pd.append([a[0] + plot_data[1][ctr][0], a[1] + plot_data[1][ctr][1]])
            elif opts.core_n == 0:
                pd = plot_data[0]
            elif opts.core_n == 1:
                pd = plot_data[1]
            import matplotlib, pylab
            for i in range(0, len(pd)):
                matplotlib.pyplot.figure()
                matplotlib.pyplot.subplot(2, 1, 1)
                matplotlib.pyplot.plot(pd[i][0])
                matplotlib.pyplot.subplot(2, 1, 2)
                matplotlib.pyplot.plot(pd[i][1])
            matplotlib.pyplot.show()

except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()

exit_clean()
