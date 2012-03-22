#!/usr/bin/env python

'''
Grabs the contents of snap blocks after the ffts, given antenna, and plots successive accumulations.

Author: Paul Prozesky
Date: 2011-09-07

Revisions:
2011-09-07  PVP Initial.
'''
import corr, time, numpy, struct, sys, logging, pylab, matplotlib

pol_list = []
report = []

def exit_fail():
    print 'FAILURE DETECTED. Log entries:\n', lh.printMessages() 
    print "Unexpected error:", sys.exc_info()
    try:
        c.disconnect_all()
    except: pass
    if verbose:
        raise
    exit()

def exit_clean():
    try:
        c.disconnect_all()
    except: pass
    exit()

def drawDataCallback():
    for p, pol in enumerate(pol_list):
        get_data(pol)
        pol['plot'].cla()
        pol['plot'].set_xlim(0, n_chans + 1)
        pol['plot'].set_xlabel('Frequency channel')
        pol['plot'].set_ylabel('Average level')
        if opts.noaccum:
            pol['plot'].set_title('FFT amplitude output for input %s, single spectrum.' % pol['ant_str'])
            dtp = pol['last_spectrum']
        else:
            pol['plot'].set_title('FFT amplitude output for input %s, averaged over %i spectra.' % (pol['ant_str'], pol['num_accs']))
            dtp = numpy.divide(pol['accumulations'], pol['num_accs'])
        if opts.logplot == True:
            pol['plot'].semilogy(dtp)
        else:
            pol['plot'].plot(dtp)
        fig.canvas.draw()
        fig.canvas.manager.window.after(opts.update_rate, drawDataCallback)

def parseAntenna(antArg):
    #import re
    #regExp = re.compile('^[0-9]{1,4}[xy]{0,2}$')
    ants = antArg.lower().replace(' ','').split(',')
    return ants

def get_data(pol):
    print 'Integrating data %i from %s:' % (pol['num_accs'], pol['ant_str'])
    print '\tGrabbing data off snap blocks...',
    if c.is_wideband():
        unpacked_vals = get_data_wb(pol)
    elif c.is_narrowband():
        if opts.buffer and opts.fine:
            unpacked_vals = get_data_nb_buffered(pol)
        elif opts.window and opts.fine:
            unpacked_vals = get_data_nb_windowed(pol)
        elif opts.quant and opts.fine:
            unpacked_vals = get_data_nb_quant(pol)
        else:
            unpacked_vals = get_data_nb(pol)
    else:
        raise RuntimeError('Mode not supported.')
    print 'done.'
    print '\tAccumulating chans...', 
    for a in exclusion_list:
        unpacked_vals[0][a] = 0
    pol['last_spectrum'] = numpy.abs(unpacked_vals[0])
    pol['accumulations'] = numpy.sum([pol['accumulations'], numpy.sum(numpy.abs(unpacked_vals), axis = 0)], axis = 0)
    pol['num_accs'] += unpacked_vals.shape[0]
    print 'done.'
    return

def get_data_wb(pol):
    #unpacked_vals = c.get_quant_snapshot(pol['ant_str'], n_spectra = 8)
    raise RuntimeError('not yet implemented')

def get_data_nb(pol):
    if opts.fine == False:
        snap_data = corr.corr_nb.get_snap_coarse_fft(c, [pol['fpga']])[0]
        unpacked_vals = numpy.array(snap_data)
    else:
        unpacked_vals = []
        offset = 0
        while len(unpacked_vals) < n_chans:
            print '(%i/%i)' % (len(unpacked_vals), n_chans),
            sys.stdout.flush()
            temp = corr.corr_nb.get_snap_fine_fft(c, fpgas = [pol['fpga']], offset = offset)
            temp = temp[0][pol['pol']]
            unpacked_vals.extend(temp)
            offset += (len(temp) * 128/8)
        length = len(unpacked_vals)
        swapped = unpacked_vals[length/2:]
        swapped.extend(unpacked_vals[0:length/2])
        unpacked_vals = numpy.array(swapped)
    unpacked_vals.shape = (len(unpacked_vals) / n_chans, n_chans)
    return unpacked_vals

def get_data_nb_buffered(pol):
    unpacked_vals = []
    offset = 0
    while len(unpacked_vals) < n_chans:
        temp = corr.corr_nb.get_snap_fine_buffer(c, fpgas = [pol['fpga']], offset = offset)
        temp = temp[0][pol['pol']]
        unpacked_vals.extend(temp)
        offset += (len(temp) * 128/8)
    fftd = numpy.fft.fft(unpacked_vals, n = n_chans).tolist()
    length = len(fftd)
    swapped = fftd[length/2:]
    swapped.extend(fftd[0:length/2])
    unpacked_vals = numpy.array(swapped)
    unpacked_vals.shape = (len(unpacked_vals) / n_chans, n_chans)
    return unpacked_vals

def get_data_nb_windowed(pol):
    unpacked_vals = []
    offset = 0
    while len(unpacked_vals) < n_chans:
        temp = corr.corr_nb.get_snap_fine_window(c, fpgas = [pol['fpga']], offset = offset)
        temp = temp[0][pol['pol']]
        unpacked_vals.extend(temp)
        offset += (len(temp) * 128/8)
    fftd = numpy.fft.fft(unpacked_vals, n = n_chans).tolist()
    length = len(fftd)
    swapped = fftd[length/2:]
    swapped.extend(fftd[0:length/2])
    unpacked_vals = numpy.array(swapped)
    unpacked_vals.shape = (len(unpacked_vals) / n_chans, n_chans)
    return unpacked_vals

def get_data_nb_quant(pol):
    unpacked_vals = []
    offset = 0
    while len(unpacked_vals) < n_chans:
        temp = corr.corr_nb.get_snap_quant(c, fpgas = [pol['fpga']], offset = offset)
        temp = temp[0][pol['pol']]
        unpacked_vals.extend(temp)
        offset += (len(temp) * 128/8)
    length = len(unpacked_vals)
    swapped = unpacked_vals[length/2:]
    swapped.extend(unpacked_vals[0:length/2])
    unpacked_vals = numpy.array(swapped)
    unpacked_vals.shape = (len(unpacked_vals) / n_chans, n_chans)
    return unpacked_vals

if __name__ == '__main__':
    from optparse import OptionParser
    p = OptionParser()
    p.set_usage('%prog [options] CONFIG_FILE')
    p.set_description(__doc__)
    p.add_option('-t', '--man_trigger', dest='man_trigger', action='store_true',        help = 'Trigger the snap block manually')   
    p.add_option('-v', '--verbose',     dest='verbose',     action='store_true',        help = 'Print raw output.')  
    p.add_option('-a', '--ant',         dest='ant',         type='str',                 help = 'Select antenna to query.', default = None)
    p.add_option('-p', '--pol',         dest='pol',         type='int',                 help = 'Polarisation to plot, default 0.', default = 0)
    p.add_option('-u', '--update_rate', dest='update_rate', type='int',                 help = 'Update rate, in ms.', default = 100)
    p.add_option('-n', '--nbsel',       dest='fine',        action='store_true',        help = 'Select which FFT to plot in narrowband mode. False for Coarse, True for Fine.', default = False)
    p.add_option('-x', '--exclude',     dest='exclude',     type='string',              help = 'COMMA-DELIMITED list of channels to exclude from the plot.', default = '')
    p.add_option('-b', '--buffer',      dest='buffer',      action='store_true',        help = 'Use the output of the fine buffer and do a soft FFT on it. Accumulate that.', default = False)
    p.add_option('-w', '--window',      dest='window',      action='store_true',        help = 'Use the output of the fine buffer, WINDOWED, and do a soft FFT on it. Accumulate that.', default = False)
    p.add_option('-l', '--logplot',     dest='logplot',     action='store_true',        help = 'Use a log scale for the y axis.', default = False)
    p.add_option('-q', '--quant',       dest='quant',       action='store_true',        help = 'Use quantised output instead.', default = False)
    p.add_option('', '--noaccum',       dest='noaccum',     action='store_true',        help = 'Do not accumulate, just output individual spectra.', default = False)
    opts, args = p.parse_args(sys.argv[1:])

    if opts.man_trigger: man_trigger = True
    else: man_trigger = False

    if args == []:
        config_file = None
    else:
        config_file = args[0]

    verbose = opts.verbose

    exclusion_list = []
    if opts.exclude.strip() != '':
        for a in opts.exclude.split(','):
            exclusion_list.append(int(a))

lh = corr.log_handlers.DebugLogHandler(35)

if opts.ant != None:
    ant_strs = parseAntenna(opts.ant)
else:
    print 'No antenna given for which to plot data.'
    exit_fail()

try:
    print 'Connecting with config %s...' % config_file,
    c = corr.corr_functions.Correlator(config_file = config_file, log_level = logging.DEBUG if verbose else logging.INFO, connect = False)
    c.connect()
    print 'done'

    if c.is_wideband():
        n_chans = c.config['n_chans']
    elif c.is_narrowband():
        if opts.fine == False:
            n_chans = c.config['coarse_chans'] #* 2
        else:
            n_chans = c.config['n_chans']
    else:
        raise RuntimeError('Operation not defined for other modes.')

    # set up the figure with a subplot for each polarisation to be plotted
    fig = matplotlib.pyplot.figure()
    for p, ant_str in enumerate(ant_strs):
        ffpga_n, xfpga_n, fxaui_n, xxaui_n, feng_input = c.get_ant_str_location(ant_str)
        pol_list.append({'ant_str': ant_str})
        pol_list[p]['fpga'] = c.ffpgas[ffpga_n]
        pol_list[p]['accumulations'] = numpy.zeros(n_chans)
        pol_list[p]['last_spectrum'] = numpy.zeros(n_chans)
        pol_list[p]['num_accs'] = 0
        pol_list[p]['pol'] = opts.pol
        pol_list[p]['plot'] = fig.add_subplot(len(ant_strs), 1, p + 1)

    # start the process    
    fig.canvas.manager.window.after(opts.update_rate, drawDataCallback)
    print 'Plot started.'
    matplotlib.pyplot.show()

except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()

exit_clean()

#end

