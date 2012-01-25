#!/usr/bin/env python

#
# Use the crs_snap data to do an n-channel fine FFT.
#
# Data out the coarse FFT is four parallel samples of 2 x f18.17 for each pol, which is 4 x 36 x 2 = 288 bits.
# This is converted down to 2 x f16.15 for each sample and only the selected pol is stored by the snap block.
# So that's 4 x 32 = 128 bits. Underneath that's four parallel freq channels, each f16.15 complex.
#
# So buffer up fine_chan of each of the specified channels and plot the FFT of that.
#

snap_len = 1024
snap_len_bytes = 8192

import optparse

options = optparse.OptionParser()
options.add_option("--verbose",         "-v", action="store_true",      help="Print extra info.", default = False)
options.add_option("--fpga",            "",     type="int",             help="Which f-engine FPGA? 0, 1, 2...", default = 0)
options.add_option("--pol",             "-p",   type="int",             help="Which pol? 0 or 1.", default = 0)
options.add_option("--coarse_chans",    "-c",   type="string",          help="A comma-delimited list of coarse channels to process.", default = "")
options.add_option("--accumulations",   "-a",   type="int",             help="How many accumulations must be done? Default: continue indefinitely.", default = -1)
options.add_option("--finechans",       "-f",   type="int",             help="Specify a different number of fine chans to that in the config file.", default = -1)
options.add_option("--readfile",        "-r",   type="string",          help="Read data from a file instead of from the devices.", default = "")
options.add_option("--writefile",       "-w",   type="string",          help="Write data to file.", default = "")
options.add_option("--buffer",          "-b",   action="store_true",    help="Use the hardware buffer output. Can only do preselected channel then.", default = False)
options.add_option("--noplot",          "",     action="store_true",    help="Don't plot the data.", default = False)
opts, args = options.parse_args()

opts.coarse_chans = opts.coarse_chans.strip()
if opts.coarse_chans == "":
    raise RuntimeError("You must specify at least one coarse channel.")

readfile = opts.readfile.strip()
writefile = opts.writefile.strip()
if readfile != "" and writefile != "":
    raise RuntimeError("Can't read from file and write to file at once. Makes no sense.")
if readfile != "":
    try:
        f = open(readfile, 'r')
    except IOError:
        raise RuntimeError("Can't read from file:", readfile)
    f.close()
    print "Setting accumulations to 1."
    opts.accumulations = 1 
if writefile != "":
    f = None
    try:
        f = open(writefile, 'r')
    except IOError:
        donothing = True
    if f != None:
        f.close()
        raise RuntimeError("Cowardly refusing to overwrite file:", writefile)
    try:
        f = open(writefile, 'w')
    except IOError:
        raise RuntimeError("Can't write to file:", writefile)

plot = True
if opts.noplot: plot = False

if args == []:
    raise RuntimeError("No corr config file specified. Please do so.") 
else:
    config_file = args[0]

import corr, logging, numpy, time, sys

def get_coarse_data(c, channels, snaps, pol):
    data = {}
    for chan in channels:
        data[chan] = []
    ctr = 0
    print '\tGrabbing snapshot: %4i/%4i' % (ctr, snaps),
    while ctr < snaps:
        print 11 * '\b', '%4i/%4i' % (ctr, snaps),
        sys.stdout.flush()
        coarse_fft_data = corr.corr_nb.get_snap_coarse_fft(c, [c.ffpgas[opts.fpga]], pol)[0]
        for chan in channels:
            d = coarse_fft_data[chan::(c.config['coarse_chans'] * 2)]
            data[chan].extend(d)
        ctr+=1
    print ''
    return data

def get_buffer_data(c, channel, pol):
    data = {}
    data[channel] = []
    ctr = 0
    snaps_to_get = c.config['n_chans'] / snap_len
    print '\tGrabbing snapshot: %4i/%4i' % (ctr, snaps_to_get),
    while ctr < snaps_to_get:
        print 11 * '\b', '%4i/%4i' % (ctr, snaps_to_get),
        sys.stdout.flush()
        snap_data = corr.corr_nb.get_snap_fine_buffer(c = c, fpgas = [c.ffpgas[opts.fpga]], offset = ctr * snap_len_bytes)[0]
        data[channel].extend(snap_data[pol])
        ctr+=1
    print ''
    return data

def get_data_from_file(filename, channels):
    print "Reading from file", filename
    sys.stdout.flush()
    f = open(filename, 'r')
    data = {}
    while True:
        try:
            d = pickle.load(f)
            for k,e in d.items():
                if data.has_key(k):
                    data[k].extend(e)
                else:
                    data[k] = e
        except EOFError:
            f.close()
            break
    for chan in channels:
        if data.keys().count(chan) == 0:
            print "\tWARNING: can't find requested channel %i in data from file, removing from channel list!" % chan
            channels.remove(chan)
    return data

try:    
    print 'Connecting to correlator...',
    c = corr.corr_functions.Correlator(config_file = config_file, log_level = logging.INFO, connect = False)
    if not c.is_narrowband():
        raise RuntimeError("Only valid for narrowband modes.") 
    c.connect()
    print 'done'

    if opts.finechans == -1:
        n_chans = c.config['n_chans']
    else:
        n_chans = opts.finechans

    print 'WARNING - this script is gonna take ages.'
    snaps_per_fine_fft = n_chans / (snap_len / (c.config['coarse_chans'] * 2))
    print 'Loading coarse data for one fine FFT. Need to read snap %i times.' % snaps_per_fine_fft

    channels = []
    if opts.coarse_chans == "all":
        channels = range(0, c.config['coarse_chans'])
    else: 
        for s in opts.coarse_chans.strip().split(','):
            channels.append(int(s))
    print 'Will get data for', channels

    if plot:
        import pylab

    import pickle
    accum_counter = 0
    accumulated = {}
    for chan in channels:
        accumulated[chan] = numpy.array(numpy.zeros(n_chans))
    while accum_counter < opts.accumulations or opts.accumulations == -1:
        print 'Reading snapshot set %i now.' % accum_counter
        sys.stdout.flush()
        data = {}

        # load data
        if readfile != "":
            data = get_data_from_file(readfile, channels)
        else:
            if opts.buffer:
                data = get_buffer_data(c, channels[0], opts.pol)
            else:
                data = get_coarse_data(c, channels, snaps_per_fine_fft, opts.pol)

        # write data to file
        if writefile != "":
            print '\tWriting to file', writefile,
            sys.stdout.flush()
            f = open(writefile, 'a')
            pickle.dump(data, f)
            f.close()
            print ', done.'
            sys.stdout.flush()
        
        # accumulate
        print 'Accumulating and FFTing...',
        sys.stdout.flush()
        for chan in channels:
            accums = len(data[chan])/n_chans
            print 'chan(%i,%i)' % (chan, accums),
            for ctr in range(0, accums):
                d = data[chan][ctr*n_chans : (ctr+1)*n_chans]
                fftd = numpy.fft.fft(d, n = n_chans)
                accumulated[chan] += numpy.array(abs(fftd))
                #pwr = (fftd.real**2 + fftd.imag**2) ** 0.5
                #accumulated[chan] += numpy.array(pwr)
        del data
        print 'done.'

        accum_counter += 1

    # update the plots
    if plot:
        print 'Plotting...',
        sys.stdout.flush()
        pylab.cla()
        for chan in channels:
            length = len(accumulated[chan])
            swapped = accumulated[chan][length/2:].tolist()
            swapped.extend(accumulated[chan][0:length/2].tolist())
            swapped = numpy.array(swapped)
            pylab.plot(swapped / accum_counter)
        pylab.show()
        print 'done.'

    c.disconnect_all()

except KeyboardInterrupt, RuntimeError:

    c.disconnect_all()

# end

