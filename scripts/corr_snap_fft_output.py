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
accum_limit = -1

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

def draw_callback():
    # get and plot the snap data
    for p, pol in enumerate(pol_list):
        get_data(pol)
        pol['plot'].cla()
        pol['plot'].set_xlim(0, pol['plot_chans'] + 1)
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
    if ((pol_list[0]['num_accs'] < accum_limit) and (accum_limit > -1)) or (accum_limit == -1): 
        fig.canvas.manager.window.after(opts.update_rate, draw_callback)

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
        if opts.coarse:
            print 'coarse FFT',
            unpacked_vals = get_data_nb_coarse_fft(pol)
        elif opts.softfft > -1:
            print 'soft fine FFT on coarse output',
            unpacked_vals = get_data_nb_soft_fine_fft_coarse(pol, selectedchan = opts.softfft)
        elif opts.softfft2 > -1:
            print 'soft fine FFT on coarse output - new method',
            unpacked_vals = get_data_nb_soft_fine_fft2_coarse(pol, selectedchan = opts.softfft2)
        elif opts.quant:
            print 'quantiser',
            unpacked_vals = get_data_nb_quant(pol)
        elif opts.sfft_buf:
            print 'soft FFT on buffer output',
            unpacked_vals = get_data_nb_soft_fft_buffer_pfb(pol, pfb = False)
        elif opts.sfft_pfb:
            print 'soft FFT on pfb output',
            unpacked_vals = get_data_nb_soft_fft_buffer_pfb(pol, pfb = True)
        else:
            print 'fine FFT',
            unpacked_vals = get_data_nb_fine_fft(pol)
    else:
        raise RuntimeError('Mode not supported.')
    print 'done.'
    print '\tAccumulating chans...', 
    for a in exclusion_list:
        unpacked_vals[0][a] = 0
    if len(pol['last_spectrum']) == 1:
        pol['last_spectrum'] = numpy.zeros(pol['plot_chans'])
        pol['accumulations'] = numpy.zeros(pol['plot_chans'])
    pol['last_spectrum'] = numpy.abs(unpacked_vals[0])
    pol['accumulations'] = numpy.sum([pol['accumulations'], numpy.sum(numpy.abs(unpacked_vals), axis = 0)], axis = 0)
    pol['num_accs'] += unpacked_vals.shape[0]
    print 'done.'
    return

def get_data_wb(pol):
    #unpacked_vals = c.get_quant_snapshot(pol['ant_str'], n_spectra = 8)
    raise RuntimeError('not yet implemented for wideband')

def get_data_nb_coarse_fft(pol):
    pol['plot_chans'] = pol['coarse_chans']
    snap_data = corr.corr_nb.get_snap_coarse_fft(c, [pol['fpga']])[0]
    unpacked_vals = numpy.array(snap_data)
    unpacked_vals.shape = (len(unpacked_vals) / pol['coarse_chans'], pol['coarse_chans'])
    return unpacked_vals

def get_data_nb_soft_fine_fft_coarse(pol, selectedchan = -1):
    '''
    Get and buffer the output of the coarse FFT output, then do a numpy FFT on the result.
    The coarse FFT snap returns both pols for a given FPGA.
    '''
    fftlength = pol['fine_chans']
    fftlength = 16
    pol['plot_chans'] = fftlength
    snapdata = corr.corr_nb.get_snap_coarse_fft(c, fpgas = [pol['fpga']], pol = pol['pol'], setup_snap = True)[0]
    requiredlen = pol['coarse_chans'] * fftlength
    if len(snapdata) >= requiredlen:
        print 'Got %i/%i values required.' % (len(snapdata), requiredlen)
    else:
        print 'Need to get %i values: ' % requiredlen,
        while(len(snapdata) < requiredlen):
            tempdata = corr.corr_nb.get_snap_coarse_fft(c, fpgas = [pol['fpga']], pol = pol['pol'], setup_snap = False)[0]
            snapdata.extend(tempdata)
            print '%i/%i, ' % (len(snapdata), requiredlen),
            sys.stdout.flush()
        print ''
    snapdata = numpy.array(snapdata)
    snapdata.shape = (fftlength, pol['coarse_chans'])
    # now do the FFT on a specific channel?
    column = snapdata[0:fftlength, selectedchan]
    fftd = numpy.fft.fft(column, n = fftlength).tolist()
    fftlen = len(fftd)
    swapped = fftd[fftlen/2:]
    swapped.extend(fftd[0:fftlen/2])
    swapped = numpy.array(swapped)
    swapped.shape = (1, fftlength)
    return swapped

def get_data_nb_soft_fine_fft2_coarse(pol, selectedchan = -1):
    '''
    Get and buffer the output of the coarse FFT output, then do a numpy FFT on the result.
    The coarse FFT snap returns both pols for a given FPGA.
    '''
    fftlength = 1024
    pol['plot_chans'] = fftlength
    snapdata = corr.corr_nb.get_snap_coarse_channel(c, fpgas = [pol['fpga']], pol = pol['pol'], channel = selectedchan, setup_snap = True)[0]
    print 'Got %i/%i values required.' % (len(snapdata), fftlength)
    fftd = numpy.fft.fft(snapdata, n = fftlength).tolist()
    fftlen = len(fftd)
    swapped = fftd[fftlen/2:]
    swapped.extend(fftd[0:fftlen/2])
    swapped = numpy.array(swapped)
    swapped.shape = (1, fftlength)
    return swapped

def get_data_nb_fine_fft(pol):
    pol['plot_chans'] = pol['fine_chans']
    unpacked_vals = []
    offset = 0
    while len(unpacked_vals) < pol['fine_chans']:
        print '(%i/%i)' % (len(unpacked_vals), pol['fine_chans']),
        sys.stdout.flush()
        temp = corr.corr_nb.get_snap_fine_fft(c, fpgas = [pol['fpga']], offset = offset, setup_snap = (offset == 0))
        temp = temp[0][pol['pol']]
        unpacked_vals.extend(temp)
        offset += (len(temp) * 128/8)
    if len(unpacked_vals) != pol['fine_chans']:
        raise RuntimeError('Needs fixing. Please.')
    length = len(unpacked_vals)
    swapped = unpacked_vals[length/2:]
    swapped.extend(unpacked_vals[0:length/2])
    unpacked_vals = numpy.array(swapped)
    unpacked_vals.shape = (len(unpacked_vals) / pol['fine_chans'], pol['fine_chans'])
    return unpacked_vals

def get_data_nb_quant(pol):
    pol['plot_chans'] = pol['fine_chans']
    unpacked_vals = []
    offset = 0
    while len(unpacked_vals) < pol['fine_chans']:
        temp = corr.corr_nb.get_snap_quant(c, fpgas = [pol['fpga']], offset = offset)
        temp = temp[0][pol['pol']]
        unpacked_vals.extend(temp)
        # each word from the snap block is 128 bits, 16 bytes. offset is given in bytes.
        offset += (len(temp) * 128/8)
    length = len(unpacked_vals)
    swapped = unpacked_vals[length/2:]
    swapped.extend(unpacked_vals[0:length/2])
    unpacked_vals = numpy.array(swapped)
    unpacked_vals.shape = (len(unpacked_vals) / pol['fine_chans'], pol['fine_chans'])
    return unpacked_vals

def get_data_nb_soft_fft_buffer_pfb(pol, pfb = False):
    fftlength = pol['fine_chans']
    fftlength = 1024
    pol['plot_chans'] = fftlength
    snapdata = corr.corr_nb.get_snap_buffer_pfb(c, fpgas = [pol['fpga']], pol = pol['pol'], setup_snap = True, pfb = pfb)[0]
    requiredlen = fftlength
    if len(snapdata) >= requiredlen:
        print 'Got %i/%i values required.' % (len(snapdata), requiredlen)
    else:
        print 'Need to get %i values: ' % requiredlen,
        while(len(snapdata) < requiredlen):
            tempdata = corr.corr_nb.get_snap_buffer_pfb(c, fpgas = [pol['fpga']], pol = pol['pol'], setup_snap = False, pfb = pfb)[0]
            snapdata.extend(tempdata)
            print '%i/%i, ' % (len(snapdata), requiredlen),
            sys.stdout.flush()
        print ''
    snapdata = numpy.array(snapdata)
    #snapdata.shape = (fftlength, pol['coarse_chans'])
    # now do the FFT on a specific channel?
    #column = snapdata[0:fftlength, selectedchan]
    fftd = numpy.fft.fft(snapdata, n = fftlength).tolist()
    fftlen = len(fftd)
    swapped = fftd[fftlen/2:]
    swapped.extend(fftd[0:fftlen/2])
    swapped = numpy.array(swapped)
    swapped.shape = (1, fftlength)
    return swapped

if __name__ == '__main__':
    from optparse import OptionParser
    p = OptionParser()
    p.set_usage('%prog [options] CONFIG_FILE')
    p.set_description(__doc__)
    p.add_option('-t', '--man_trigger', dest='man_trigger', action='store_true',        help = 'Trigger the snap block manually')   
    p.add_option('-v', '--verbose',     dest='verbose',     action='store_true',        help = 'Print raw output.')  
    p.add_option('-a', '--ant',         dest='ant',         type='str',                 help = 'Select antenna to query.', default = None)
    p.add_option('-p', '--pol',         dest='pol',         type='int',                 help = 'Polarisation to plot, default 0.', default = 0)
    # what do we want to plot?
    p.add_option('', '--coarse',            dest='coarse',      action='store_true',    help = 'Output of coarse FFT.', default = False)
    p.add_option('', '--soft_fine_fft',     dest='softfft',     type='int',             help = 'Channel on which to do a soft FFT on the output of the coarse FFT.', default = -1)
    p.add_option('', '--soft_fine_fft2',    dest='softfft2',    type='int',             help = 'Channel on which to do a soft FFT on the output of the coarse FFT - using new debug functionality.', default = -1)
    p.add_option('', '--fine',              dest='fine',        action='store_true',    help = 'Output of fine FFT.', default = False)
    p.add_option('', '--quant',             dest='quant',       action='store_true',    help = 'Quantiser output.', default = False)
    p.add_option('', '--sfft_buffer',       dest='sfft_buf',    action='store_true',    help = 'TEMPDEBUG: soft fft on the buffer output.', default = False)
    p.add_option('', '--sfft_pfb',          dest='sfft_pfb',    action='store_true',    help = 'TEMPDEBUG: soft fft on the pfb output.', default = False)
    # other options
    p.add_option('-u', '--update_rate', dest='update_rate', type='int',                 help = 'Update rate, in ms.', default = 100)
    p.add_option('-x', '--exclude',     dest='exclude',     type='string',              help = 'COMMA-DELIMITED list of channels to exclude from the plot.', default = '')
    p.add_option('-l', '--logplot',     dest='logplot',     action='store_true',        help = 'Use a log scale for the y axis.', default = False)
    p.add_option('', '--noaccum',       dest='noaccum',     action='store_true',        help = 'Do not accumulate, just output individual spectra.', default = False)
    p.add_option('', '--accum_limit',   dest='accum_limit', type='int',                 help = 'Stop after n accumulations.', default = -1)
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

    accum_limit = opts.accum_limit

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

    # set up the figure with a subplot for each polarisation to be plotted
    fig = matplotlib.pyplot.figure()

    for p, ant_str in enumerate(ant_strs):
        ffpga_n, xfpga_n, fxaui_n, xxaui_n, feng_input = c.get_ant_str_location(ant_str)
        pol_list.append({'ant_str': ant_str})
        pol_list[p]['fpga'] = c.ffpgas[ffpga_n]
        pol_list[p]['accumulations'] = numpy.zeros(1)
        pol_list[p]['last_spectrum'] = numpy.zeros(1)
        pol_list[p]['num_accs'] = 0
        pol_list[p]['pol'] = opts.pol
        pol_list[p]['plot'] = fig.add_subplot(len(ant_strs), 1, p + 1)
        pol_list[p]['coarse_chans'] = c.config['coarse_chans']
        pol_list[p]['fine_chans'] = c.config['n_chans']
        pol_list[p]['plot_chans'] = -1 # will be set by the data_get function depending on the options given

    # start the process    
    fig.canvas.manager.window.after(opts.update_rate, draw_callback)
    print 'Plot started.'
    matplotlib.pyplot.show()

except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()

exit_clean()

#end

