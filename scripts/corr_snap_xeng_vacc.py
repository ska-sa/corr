#!/usr/bin/env python
'''
Grabs the contents of "snap_xeng0" (one per FPGA) at the output of the X eng and prints any non-zero values.
Assumes the correlator is already initialsed and running etc.

NOTE: Only good for 4 bit X engines with demux of 8 and accumulation length of 128.

Author: Jason Manley\n
Revisions:\n
2011-10-03: PVP New snap block support.
2010-08-05: JRM Mods to support corr-0.5.0  
2010-07-29: PVP Cleanup as part of the move to ROACH F-Engines. Testing still needed.\n
2009------: JRM Initial revision.\n
'''
import corr, time, numpy, pylab, struct, sys, logging

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

def raw2fp(num, nbits = 4):
    return float(((numpy.int8(num << nbits) >> nbits))) / (2**(nbits-1))

def unpack32bit(num):
    pol01 = raw2fp((num >> 12) & 0x0f) + (1j * raw2fp((num >>  8) & 0x0f))
    pol11 = raw2fp((num >>  4) & 0x0f) + (1j * raw2fp((num >>  0) & 0x0f))
    return [pol00, pol01], [pol10, pol11]

if __name__ == '__main__':
    from optparse import OptionParser

    p = OptionParser()
    p.set_usage('%prog [options] CONFIG_FILE')
    p.add_option('-s', '--snap', dest='snap', type='int', default=0, help='Pull data from the xeng (0) or vacc (1) snap blocks. Default: 0.')
    p.add_option('-v', '--verbose', dest='verbose', action='store_true', help='Print all the decoded (including zero valued) results (be verbose).')
    p.add_option('-x', '--xfpga', dest='xfpga', type='int', default=-1, help='Which x-engine fpga should be quried. Default is all.')
    p.add_option('-o', '--ch_offset', dest='ch_offset', type='int', default=0, help='Start capturing at specified channel offset. Default is 0.')
    p.add_option('-c', '--channel', dest='channel', type='int', default=-1, help='Capture a specific channel. This will automatically choose the correct x-engine.')

    p.set_description(__doc__)
    opts, args = p.parse_args(sys.argv[1:])

    if args==[]:
        config_file=None
    else:
        config_file=args[0]
    verbose=opts.verbose

    if opts.snap == 0:
        dev_name = 'snap_xeng0'
    elif opts.snap == 1:
        dev_name = 'snap_vacc0'
    else:
        raise RuntimeError('Expected 0 or 1 for option -s.')

try:
    print 'Connecting...',
    c=corr.corr_functions.Correlator(config_file=config_file,log_level=logging.DEBUG if verbose else logging.INFO,connect=False)
    c.connect()
    print 'done'

    binary_point = c.config['feng_fix_pnt_pos']
    packet_len = c.config['10gbe_pkt_len']
    n_chans = c.config['n_chans']
    n_chans_per_x = c.config['n_chans_per_x']
    num_bits = c.config['feng_bits']
    adc_bits = c.config['adc_bits']
    adc_levels_acc_len = c.config['adc_levels_acc_len']
    x_per_fpga = c.config['x_per_fpga']
    n_ants = c.config['n_ants']
    xeng_acc_len = c.config['xeng_acc_len']
    n_bls = c.config['n_bls']

    report = dict()

    # work out offsets and what-not
    if opts.channel != -1:
        xeng_num = opts.channel / n_chans_per_x
        if xeng_num % 2 != 0:
            raise RuntimeError('Can\'t show channel %i on x-engine %i, only the even-numbered x-engines have snap blocks.' % (opts.channel, xeng_num))
        xeng_fpga = xeng_num / 2
        fpgas = [c.xfpgas[xeng_fpga]]
        offset_bytes = ((opts.channel - (xeng_num * n_chans_per_x)) * n_bls) * 4 * 2
        print 'Channel %i found on fpga %i, x-engine %i' % (opts.channel, xeng_num, xeng_fpga)
    else:
        if opts.xfpga == -1: fpgas = c.xfpgas
        else: fpgas = [c.xfpgas[opts.xfpga]]
        if c.config['xeng_format'] == 'inter':
            offset_bytes = opts.ch_offset * n_bls * 4 * 2
        else:
            offset_bytes = opts.ch_offset * n_bls * 4 * 2

    if num_bits != 4:
        print 'ERR: this script is only written to interpret 4 bit data. Your F engine outputs %i bits.' % num_bits
        exit_fail()
    if xeng_acc_len != 128:
        print 'ERR: this script is only written to interpret data from X engines with acc length of 128 due to hardcoded bitwidth growth limitations. Your X engine accumulates for %i samples.'%xeng_acc_len
        exit_fail()


    print '------------------------'
    print 'Triggering capture at byte offset %i...' % (offset_bytes),
    sys.stdout.flush()
    bram_dmp = corr.snap.snapshots_get(fpgas, dev_name, man_trig = False, wait_period = 2, offset = offset_bytes)
    print 'done.'

    print 'Unpacking bram contents...'
    # hardcode unpack of 16 bit values. Assumes bitgrowth of log2(128)=7 bits and input of 4_3 * 4_3.
    sys.stdout.flush()
    bram_data = []
    for f, fpga in enumerate(fpgas):
        print " Unpacking %i values from %s." % (len(bram_dmp['data'][f]), c.xsrvs[f])
        if len(bram_dmp['data'][f]) > 0:
            bram_data.append(struct.unpack('>%ii' % (len(bram_dmp['data'][f]) / 4), bram_dmp['data'][f]))
        else:
            print " Got no data back for %s." % c.xsrvs[f]
            bram_data.append([])
    print 'Done.'
    print '========================\n'

    for xeng, fpga in enumerate(fpgas):
        print '--------------------'
        print '\nX-engine %i' % xeng
        print '--------------------'
        for li in range(0, len(bram_data[xeng]) / 2):
            # index over complex numbers in bram
            index = (bram_dmp['offsets'][xeng]/(4*2)) + li
            bls_index = index  % n_bls
            if c.config['xeng_format'] == 'inter':
                freq = (index / n_bls) * x_per_fpga * len(fpgas) + xeng
            else:
                freq = (index / n_bls) + x_per_fpga * xeng * c.config['n_chans']/c.config['n_xeng']
            #print '(%i,%i,%i,%i)' % (li, index, bls_index, freq),
            i, j = c.get_bl_order()[bls_index]
            # data is a 128-bit number that was demuxed into 8 16.6 numbers
            real_val = bram_data[xeng][li * 2]
            imag_val = bram_data[xeng][li * 2 + 1]
            if (real_val != 0) or (imag_val != 0) or opts.verbose:
                print '[%s] [%4i,%4i]: Freq: %i. bls: %s_%s. Raw value: 0x%05x + 0x%05xj (%6i + %6ij).'%(c.xsrvs[xeng], index, bls_index, freq, i, j, real_val, imag_val, real_val, imag_val)
        print 'Done with %s, X-engine %i.'%(c.xsrvs[xeng],xeng)
    print 'Done with all.'

except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()

exit_clean()

