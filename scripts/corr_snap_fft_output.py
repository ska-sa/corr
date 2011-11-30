#!/usr/bin/env python

'''
Grabs the contents of "snap_xaui" for a given antenna and plots successive accumulations.

Author: Paul Prozesky
Date: 2011-09-07

Revisions:
2011-09-07  PVP Initial.
'''
import corr, time, numpy, struct, sys, logging, pylab, matplotlib

polList = []
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
    for p, pol in enumerate(polList):
        get_data(pol)
        pol['plot'].cla()
        pol['plot'].set_xlim(0, n_chans + 1)
        pol['plot'].set_title('FFT amplitude output for input %s, averaged over %i spectra.' % (pol['ant_str'], pol['num_accs']))
        pol['plot'].set_xlabel('Frequency channel')
        pol['plot'].set_ylabel('Average level')
        pol['plot'].plot(numpy.divide(pol['accumulations'], pol['num_accs']))
        fig.canvas.draw()
        fig.canvas.manager.window.after(opts.update_rate, drawDataCallback)

def parseAntenna(antArg):
    import re
    #regExp = re.compile('^[0-9]{1,4}[xy]{0,2}$')
    ants = antArg.lower().replace(' ','').split(',')
    return ants

def get_data(pol):
    print 'Integrating data %i from %s:' % (pol['num_accs'], pol['ant_str'])
    print ' Grabbing data off snap blocks...',
    if c.is_wideband():
        #unpacked_vals = c.get_quant_snapshot(pol['ant_str'], n_spectra = 8)
        raise RuntimeError('not yet implemented')
    elif c.is_narrowband():
        if opts.fine == False:
            unpacked_vals = numpy.array(corr.corr_nb.get_coarse_fft_snap(c, pol['ant_str']))
        else:
            unpacked_vals = numpy.array(corr.corr_nb.get_fine_fft_snap(c, pol['ant_str']))
        unpacked_vals.shape = (len(unpacked_vals) / n_chans, n_chans)
    else:
        raise RuntimeError('Mode not supported.')
    print 'done.'
    print ' Accumulating...', 
    pol['accumulations'] = numpy.sum([pol['accumulations'], numpy.sum(numpy.abs(unpacked_vals), axis = 0)], axis = 0)
    pol['num_accs'] += unpacked_vals.shape[0]
    print 'done.'
    return

if __name__ == '__main__':
    from optparse import OptionParser
    p = OptionParser()
    p.set_usage('%prog [options] CONFIG_FILE')
    p.set_description(__doc__)
    p.add_option('-t', '--man_trigger', dest='man_trigger', action='store_true',
        help='Trigger the snap block manually')   
    p.add_option('-v', '--verbose', dest='verbose', action='store_true',
        help='Print raw output.')  
    p.add_option('-a', '--ant', dest='ant', type='str', default=None,
        help='Select antenna to query.')
    p.add_option('-u', '--update_rate', dest='update_rate', type='int', default=100,
        help='Update rate, in ms.')
    p.add_option('-n', '--nbsel', dest='fine', action='store_true', default=False,
        help='Select which FFT to plot in narrowband mode. False for Coarse, True for Fine.')
    opts, args = p.parse_args(sys.argv[1:])

    if opts.man_trigger: man_trigger = True
    else: man_trigger = False

    if args==[]:
        config_file=None
    else:
        config_file=args[0]
    verbose=opts.verbose

lh = corr.log_handlers.DebugLogHandler(35)
if opts.ant != None:
    ant_strs = parseAntenna(opts.ant)
else:
    print 'No antenna given for which to plot data.'
    exit_fail()

try:
    print 'Connecting...',
    c = corr.corr_functions.Correlator(config_file = config_file, log_level = logging.DEBUG if verbose else logging.INFO, connect = False)
    c.connect()
    print 'done'

    if c.is_wideband():
        n_chans = c.config['n_chans']
    elif c.is_narrowband():
        if opts.fine == False:
            n_chans = c.config['coarse_chans'] * 2
        else:
            n_chans = c.config['n_chans']
    else:
        raise RuntimeError('Operation not defined for other modes.')

    # set up the figure with a subplot for each polarisation to be plotted
    fig = matplotlib.pyplot.figure()
    for p, ant_str in enumerate(ant_strs):
        if not ant_str in c.config._get_ant_mapping_list():
            print 'Unrecognised input %s. Must be in ' %(pol),c.config._get_ant_mapping_list()
            exit_clean()
        polList.append({'ant_str':ant_str})
        polList[p]['accumulations'] = numpy.zeros(n_chans)
        polList[p]['num_accs'] = 0
        polList[p]['plot'] = fig.add_subplot(len(ant_strs), 1, p + 1)

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

