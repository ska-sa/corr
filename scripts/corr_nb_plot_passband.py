#!/usr/bin/python
"""
Capture data from all coarse channels in a narrowband correlator mode. Must be initialised and EQ-set first.
"""

import logging, sys, time

logging.basicConfig(level = logging.WARN)

def baseline_to_tuple(h5file, baseline):
    l = h5file['bls_ordering'].value[0][baseline].tolist()
    return (l[0], l[1])

def tuple_to_baseline(h5file, t):
    for n, b in enumerate(h5file['bls_ordering'].value[0]):
        l = b.tolist()
        if t == (l[0], l[1]):
            return n
    return -1

if __name__ == '__main__':
    from optparse import OptionParser
    p = OptionParser()
    p.set_usage('%prog [options] [CUSTOM_CONFIG_FILE]')
    p.set_description(__doc__)
    p.add_option('', '--noplot', dest = 'noplot', action = 'store_true', default = False, help = 'Do not plot.')
    p.add_option('', '--plotonly', dest = 'plotonly', action = 'store_true', default = False, help = 'Plot only using exisintg data in the current directory.')
    p.add_option('-t', '--time', dest = 'capture_time', type = 'int', default = 20, help = 'Time for which data should be captured for each channel.')
    p.add_option('-b', '--baseline', dest = 'baseline', type = 'int', default = 0, help = 'Baseline to plot.')
    p.add_option('-a', '--disable_autoscale', dest = 'acc_scale', action = 'store_false', default = True, help = 'Do not autoscale the data by dividing down by the number of accumulations.  Default: Scale back by n_accs.')
    p.add_option('-v', '--verbose', dest = 'verbose', action = 'store_true', default = False, help = 'Be verbose about errors.')
    opts, args = p.parse_args(sys.argv[1:])
    if args == []:
        config_file = None
    else:
        config_file = args[0]

# record the data
if not opts.plotonly:
    if config_file == None:
        raise RuntimeError('A config file is necessary to log data.')

    import corr, spead

    print 'Parsing config file...',
    sys.stdout.flush()
    c = corr.corr_functions.Correlator(config_file = config_file, log_level = logging.DEBUG if opts.verbose else logging.WARN, connect = False)
    c.connect()
    print 'done.'

    # check for narrowband
    if not c.is_narrowband():
        raise RuntimeError('This script can only be run on narrowband correlators.')

    # stop transmission first off
    c.tx_stop()

    # loop through all the channels
    start_time = time.time()
    for channel in range(0, c.config['coarse_chans']):
        filename = 'channel_%03i.h5' % channel
        print 'Writing data for channel %i to file %s.' % (channel, filename)
        sys.stdout.flush()

        # select the coarse channel and wait a bit
        corr.corr_nb.channel_select(c, specific_chan = channel)
        time.sleep(2)

        # start the thread to receive the SPEAD data
        crx = corr.rx.CorrRx(mode = c.config['xeng_format'], data_port = c.config['rx_udp_port'],
            sd_ip = c.config['sig_disp_ip_str'], sd_port = c.config['sig_disp_port'], acc_scale = opts.acc_scale,
            filename = filename, log_level = logging.DEBUG if opts.verbose else logging.ERROR)
        try:
            crx.daemon = True
            crx.start()
            time.sleep(2)
            c.spead_issue_all()
            c.tx_start()
            timedout = False
            s_time = time.time()
            while(crx.isAlive() and (not timedout)):
                if time.time() - s_time > opts.capture_time:
                    timedout = True
                    raise Exception 
                time.sleep(0.2)
            print 'RX process ended.'
            crx.join()
        except Exception:
            c.tx_stop()
            time.sleep(2)
            print 'Timeout, moving to next channel.'
        except KeyboardInterrupt:
            print 'Stopping.'

    print 'Done, wrote %i channels in %.3f seconds.' % (c.config['coarse_chans'], time.time() - start_time)
    c.disconnect_all()
# end

# plot
if not opts.noplot: 
    import numpy, pylab, os, h5py

    h5files = []
    files = os.listdir('.')
    for f in files:
        if f.endswith('.h5'): h5files.append(f)
    h5files.sort()

    # are there any h5 files?
    if len(h5files) <= 0:
        raise RuntimeError('No H5 files to process.')

    # get metadata from the first file
    f = h5py.File(h5files[0], 'r')
    mdata = {}
    mdata['coarse_chans'] = f['coarse_chans'].value[0]
    mdata['n_chans'] = f['n_chans'].value[0]

    # check that the baseline exists
    baseline_str = baseline_to_tuple(f, opts.baseline)
    baseline = opts.baseline
    print 'Processing baseline %i, %s' %(baseline, baseline_str)

    x_phase = numpy.zeros(mdata['coarse_chans'] * (mdata['n_chans'] - 10))
    x_mag = numpy.zeros(mdata['coarse_chans'] * (mdata['n_chans'] - 10))
    ctr = 0
    last_chan = -1
    for fname in h5files:
        f = h5py.File(fname, 'r')
        chan = f['current_coarse_chan'].value[0]
        if chan <= last_chan:
            raise RuntimeError('coarse channel %i does not make sense, last one was %i.' % (chan, last_chan))
        last_chan = chan
        if f['coarse_chans'].value[0] != mdata['coarse_chans']:
            raise RuntimeError('Can only compare data from the same correlator output. coarse_chans differs from first file checked.') 
        if f['n_chans'].value[0] != mdata['n_chans']:
            raise RuntimeError('Can only compare data from the same correlator output. n_chans differs from first file checked.') 
        s = f['xeng_raw']
        d = numpy.zeros(mdata['n_chans'])
        for data in s:
            temp = numpy.vectorize(complex)(data[:,baseline,0], data[:,baseline,1]) 
            d = d + temp
        #pylab.plot(numpy.unwrap(numpy.angle(d)))
        si = ctr * (mdata['n_chans']-10)
        d = d[5:mdata['n_chans']-5]
        #print si, ctr, len(d), si+mdata['n_chans']-10
        x_phase[si:si+mdata['n_chans']-10] = numpy.angle(d[0:mdata['n_chans']-10])
        x_mag[si:si+mdata['n_chans']-10] = d[0:mdata['n_chans']-10]
        ctr += 1
        print '.',
        sys.stdout.flush()
    print ''

    # plot
    pylab.subplot(2,1,1)
    pylab.title('magnitude')
    pylab.semilogy(x_mag)
    pylab.subplot(2,1,2)
    pylab.title('phase')
    pylab.plot(x_phase)
    pylab.show()

# end
