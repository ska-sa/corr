#!/usr/bin/env python

'''
Grabs the contents of "snap_xaui" for a given antenna and plots successive accumulations.
Does not use the standard 'corr_functions' error checking.
Assumes 4 bit values for power calculations.
Assumes the correlator is already initialsed and running etc.

Author: Jason Manley
Date: 2009-07-01

Revisions:
2011-06-29  JRM Port to new snap.py
2010-11-24  PP  Fix to plotting
                Ability to plot multiple antennas
2010-07-22: JRM Mods to support ROACH based F engines (corr-0.5.0)
2010-02-01: JRM Added facility to offset capture point.
                Added RMS printing and peak bits used.
2009-07-01: JRM Ported to use corr_functions connectivity
                Fixed number of bits calculation

'''
import corr, time, numpy, struct, sys, logging, pylab, matplotlib

polList = []
report = []
logscale = False

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
        pol['plot'].set_xlim(0, c.config['n_chans'] + 1)
        pol['plot'].set_title('Quantiser amplitude output for input %s, averaged over %i spectra.' % (pol['ant_str'], pol['num_accs']))
        pol['plot'].set_xlabel('Frequency channel')
        pol['plot'].set_ylabel('Average power level')
        if logscale:
            pol['plot'].semilogy(numpy.divide(pol['accumulations'], pol['num_accs']))
        else:
            pol['plot'].plot(numpy.divide(pol['accumulations'], pol['num_accs']))
        fig.canvas.draw()
        fig.canvas.manager.window.after(100, drawDataCallback)

def parseAntenna(antArg):
    import re
    #regExp = re.compile('^[0-9]{1,4}[xy]{0,2}$')
    ants = antArg.lower().replace(' ','').split(',')
    return ants

def get_data(pol):
    print 'Integrating data %i from %s:' % (pol['num_accs'], pol['ant_str'])
    print ' Grabbing data off snap blocks...',
    sys.stdout.flush()
    unpacked_vals, spectra = c.get_quant_snapshot(pol['ant_str'], n_spectra = 1)
    print 'done.'
    print ' Accumulating...',
    sys.stdout.flush()
    unpacked_vals = numpy.square(numpy.abs(unpacked_vals))
    if spectra > 1:
        unpacked_vals = numpy.sum(unpacked_vals, axis = 0)
    pol['accumulations'] = numpy.sum([pol['accumulations'], unpacked_vals], axis = 0)
    pol['num_accs'] += spectra
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
    p.add_option('-p', '--noplot', dest='noplot', action='store_true',
        help='Do not plot averaged spectrum.')  
    p.add_option('-a', '--ant', dest='ant', type='str', default=None,
        help='Select antenna to query.')
    p.add_option('-l', '--log', dest='log', action='store_true', default=False,
        help='Plot on a log scale.')
    opts, args = p.parse_args(sys.argv[1:])

    if opts.man_trigger: man_trigger = True
    else: man_trigger = False

    if args == []:
        config_file = None
    else:
        config_file = args[0]
    verbose = opts.verbose

lh = corr.log_handlers.DebugLogHandler(35)
if opts.ant != None:
    ant_strs = parseAntenna(opts.ant)
else:
    print 'No antenna given for which to plot data.'
    exit_fail()

logscale = opts.log

try:
    print 'Connecting...',
    c = corr.corr_functions.Correlator(config_file = config_file, log_level = logging.DEBUG if verbose else logging.INFO, connect = False)
    c.connect()
    print 'done'

    binary_point = c.config['feng_fix_pnt_pos']
    packet_len = c.config['10gbe_pkt_len']
    n_chans = c.config['n_chans']
    num_bits = c.config['feng_bits']
    adc_bits = c.config['adc_bits']
    adc_levels_acc_len = c.config['adc_levels_acc_len']

    if num_bits != 4:
        print 'This script is only written to work with 4 bit quantised values.'
        exit_clean()

    # set up the figure with a subplot for each polarisation to be plotted
    fig = matplotlib.pyplot.figure()
    for p, ant_str in enumerate(ant_strs):
        if not ant_str in c.config._get_ant_mapping_list():
            print 'Unrecognised input %s. Must be in ' % p, c.config._get_ant_mapping_list()
            exit_clean()
        polList.append({'ant_str':ant_str})
        polList[p]['accumulations'] = numpy.zeros(c.config['n_chans'])
        polList[p]['num_accs'] = 0
        polList[p]['plot'] = fig.add_subplot(len(ant_strs), 1, p + 1)

    # start the process    
    fig.canvas.manager.window.after(100, drawDataCallback)
    print 'Plot started.'
    matplotlib.pyplot.show()

except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()

exit_clean()

#end

