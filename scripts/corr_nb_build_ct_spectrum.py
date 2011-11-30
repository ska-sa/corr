#!/usr/bin/env python

'''
Uses the "fine" snap block to capture corner-turner data on the F engines and rebuild the spectrum from there.
Assumes 4 bit values for power calculations.
Assumes the correlator is already initialsed and running.

NOTE: the snap block data width is 32-bit, so that's only 2 samples x 2 pols x 4.3 complex data. 128 values per frequency means 128/2 snap block words per frequency.

Author: Paul Prozesky

Revisions:
2011-09-21: PVP Initial version.
'''
import corr, time, numpy, struct, sys, logging

snap_name = 'fine_snap_d'

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
    pol00 = raw2fp((num >> 28) & 0x0f) + (1j * raw2fp((num >> 24) & 0x0f))
    pol10 = raw2fp((num >> 20) & 0x0f) + (1j * raw2fp((num >> 16) & 0x0f))
    pol01 = raw2fp((num >> 12) & 0x0f) + (1j * raw2fp((num >>  8) & 0x0f))
    pol11 = raw2fp((num >>  4) & 0x0f) + (1j * raw2fp((num >>  0) & 0x0f))
    return [pol00, pol01], [pol10, pol11]

if __name__ == '__main__':
    from optparse import OptionParser
    p = OptionParser()
    p.set_usage('%prog [options] CONFIG_FILE')
    p.set_description(__doc__)
    p.add_option('-v', '--verbose', dest='verbose', action='store_true',
        help='Print raw output.')
    p.add_option('-f', '--fengine', dest='fengine', type='int', default=-1,
        help='F-engine to read. Default is -1, all.')
    opts, args = p.parse_args(sys.argv[1:])
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
    n_chans = c.config['n_chans']
    num_bits = c.config['feng_bits']
    if num_bits != 4:
        print 'This script is only written to work with 4 bit quantised values.'
        raise KeyboardInterrupt
    if opts.fengine == -1: fpgas = c.ffpgas
    else: fpgas = [c.ffpgas[opts.fengine]]
    # set up the path to the corner-turner snap output
    corr.corr_functions.write_masked_register(fpgas, corr.corr_nb.register_fengine_fine_control, quant_snap_select = 2)
    reports = dict()
    spectra = dict()
    for n, f in enumerate(fpgas):
        reports[n] = dict()
        spectra[n] = dict()
        spectra[n][0] = dict()
        spectra[n][1] = dict()
    n_xeng = 2**2
    snap_depth_w = 2**13
    values_per_fchan = 128
    values_per_sword = 2
    bytes_per_sword = 4
    sword_per_fchan = values_per_fchan / values_per_sword
    fchan_per_snap = snap_depth_w / sword_per_fchan
    fchan_lookup = []
    for r in range(0, n_chans / n_xeng): fchan_lookup.extend(range(r, n_chans, n_chans / n_xeng))
    up32 = dict()
    for n, f in enumerate(fpgas): up32[n] = []
    # grab the data and decode it
    print 'Grabbing and processing the spectrum data from corner-turner output snap block (offset/%i)... %5i' % (n_chans, 0),
    for offset in range(0, n_chans / fchan_per_snap):
    #for offset in range(0, 1):
        print 7 * '\b', '%5i' % (offset * fchan_per_snap),
        sys.stdout.flush()
        dataFine = corr.snap.snapshots_get(fpgas, dev_names = 'fine_snap_d', man_trig = False, man_valid = False, wait_period = 3, offset = offset * snap_depth_w * 4, circular_capture = False)
        for n, d in enumerate(dataFine['data']): up32[n].extend(list(struct.unpack('>%iI' % (snap_depth_w*4/4), d)))
    print ''
    # process the 32-bit numbers and unscramble the order
    print 'Processing %i frequency channels in %i x %i bytes: %5i' % (n_chans, len(up32), len(up32[0])*bytes_per_sword, 0),
    starttime = time.time()
    freq_coverage = []
    for f in range(0, len(up32[0]) / sword_per_fchan):
        start_index = f * sword_per_fchan
        #print '%i(%i)' % (f, fchan_lookup[f]),
        print 7 * '\b', '%5i' % f,
        sys.stdout.flush()
        for n, updata in enumerate(up32):
            pol0 = []
            pol1 = []
            for r in range(0, sword_per_fchan):
                a, b = unpack32bit(up32[n][start_index + r])
                pol0.extend(a)
                pol1.extend(b)
            spectra[n][0][fchan_lookup[f]] = numpy.average(numpy.sqrt(numpy.real(pol0)**2 + numpy.imag(pol0)**2))
            spectra[n][1][fchan_lookup[f]] = numpy.average(numpy.sqrt(numpy.real(pol1)**2 + numpy.imag(pol1)**2))
        freq_coverage.append(fchan_lookup[f])
    print ''
    print 'That took %i seconds.' % (time.time() - starttime)
    for f in range(0, n_chans):
        if not freq_coverage.__contains__(f): raise RuntimeError('Missing frequency %i.' % f)
    import matplotlib, pylab
    for i in range(0, len(spectra)):
        matplotlib.pyplot.figure()
        matplotlib.pyplot.subplot(2, 1, 1)
        matplotlib.pyplot.plot(spectra[i][0].values())
        matplotlib.pyplot.subplot(2, 1, 2)
        matplotlib.pyplot.plot(spectra[i][1].values())
    matplotlib.pyplot.show()

except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()

exit_clean()

