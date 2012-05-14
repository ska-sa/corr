#!/usr/bin/env python

'''
Plots a histogram of the quantised values from a specified antenna and pol.\n
\n
Revisions:\n
2010-12-12  JRM: Attempt to get X-axes to stay static at -1 to 1.
2010-11-16: PVP: Working with 4 bits fixed (affects number of bins). Need reconfigurable dp and number of quant bits.
2010-08-06: JRM: Initial version based on corr_adc_hist.py from Paul.\n
'''
import matplotlib, time, corr, numpy, struct, sys, pylab, os, logging

# exit cleanly
def exit_fail():
    print 'FAILURE DETECTED. Log entries:\n', lh.printMessages()
    print "Unexpected error:", sys.exc_info()
    try:
        c.disconnect_all()
    except:
        pass
    exit()
def exit_clean():
    try:
        c.disconnect_all()
    except:
        pass
    exit()

# main
if __name__ == '__main__':
    from optparse import OptionParser
    p = OptionParser()
    p.set_usage(__file__ + ' [options] CONFIG FILE')
    p.add_option('-v', '--verbose', dest = 'verbose', action = 'store_true', help = 'Print raw output.')
    p.add_option('-a', '--antenna', dest = 'antAndPol', action = 'store', help = 'Specify an antenna and pol for which to get ADC histograms in the format defined in /var/run/corr/antenna_mapping. Default is, eg, 3x giving pol x for antenna three and 27y will give pol y for antenna 27. 3x,27y will do pol \'x\' of antenna three and pol \'y\' of antenna 27.')
    p.add_option('-c', '--compare', dest = 'comparePlots', action = 'store_true', help = 'Compare plots directly using the same y-axis for all plots.')
    p.set_description(__doc__)
    opts, args = p.parse_args(sys.argv[1:])

    if args==[]:
        config_file=None
    else:
        config_file=args[0]
    verbose=opts.verbose

# parse the antenna argument passed to the program
def parseAntenna(antArg):
    import re
    #regExp = re.compile('^[0-9]{1,4}[xy]{0,2}$')
    ants = antArg.lower().replace(' ','').split(',')
    return ants
    #plotList = []
    #for ant in ants:
    #    if not regExp.search(ant):
    #        print '\'' + ant + '\' is not a valid -a argument!\nExiting.'
    #        exit()
    #    antennaNumber = int(ant.replace('x', '').replace('y', ''))
    #    if (ant.find('x') < 0) and (ant.find('y') < 0):
    #        ant = ant + 'xy'
    #    if ant.find('x') > 0:
    #        plotList.append({'antenna':antennaNumber, 'pol':'x'})
    #    if ant.find('y') > 0:
    #        plotList.append({'antenna':antennaNumber, 'pol':'y'})
    #return plotList


# the function that gets data given a required polarisation
def getUnpackedData(requiredPol):
    antLocation = c.get_ant_str_location(requiredPol)
    # which fpga do we need?
    requiredFpga = antLocation[0]
    # get the data
    unpacked_vals = corr.snap.get_quant_snapshot(correlator = c, ant_str = requiredPol, man_trig = True, man_valid = True, wait_period = 0.1)
    return unpacked_vals, requiredFpga

# make the log handler
lh = corr.log_handlers.DebugLogHandler(35)

# check the specified antennae, if any
polList = []
if opts.antAndPol != None:
    polList = parseAntenna(opts.antAndPol)
    #polList = opts.antAndPol
else:
    print 'No antenna given for which to plot data.'
    exit_fail()

try:    
    print 'Connecting...',
    c = corr.corr_functions.Correlator(config_file = config_file, log_handler = lh, log_level = logging.DEBUG if verbose else logging.INFO, connect = False)
    c.connect()
    print 'done'

    # some configuration from the config file
    quantBits = c.config['feng_bits']    
    binaryPoint = c.config['feng_fix_pnt_pos']
    
    if quantBits != 4: 
        print 'This script is only designed to work with 4-bit quantised correlators. Yours has %i bits!'%quantBits

    # set up the figure with a subplot for each polarisation to be plotted
    fig = matplotlib.pyplot.figure()

    # create the subplots
    subplots = []
    numberOfPolarisations = len(polList)
    for p, pol in enumerate(polList):
        realPlot = matplotlib.pyplot.subplot(numberOfPolarisations, 2, (p * 2) + 1)
        imagPlot = matplotlib.pyplot.subplot(numberOfPolarisations, 2, (p * 2) + 2)
        subplots.append([realPlot, imagPlot])

    # callback function to draw the data for all the required polarisations
    def drawDataCallback(comparePlots):
        maxYReal = -10000000
        maxYImag = -10000000
        dataLabel = ["real", "imag"]

        # add the data to the subplots
        for p, pol in enumerate(polList):
            unpacked_vals, ffpga = getUnpackedData(pol)
            data = []
            data.append([val.real for val in unpacked_vals])
            data.append([val.imag for val in unpacked_vals])
            globalHistMaxY = [0, 0]
            # real and imag per pol
            for d in 0, 1:
                subplots[p][d].cla()
                subplots[p][d].set_xlim(-1, 1)
                histData, bins, patches = subplots[p][d].hist(data[d], bins = (2**quantBits), range = (-1, 1))
                subplots[p][d].set_title('ant %s %s' % (pol, dataLabel[d]))
                subplots[p][d].set_xlim(-1, 1)
                maxHistData = max(histData)
                globalHistMaxY[d] = max(globalHistMaxY[d], maxHistData)
                if not comparePlots:
                    matplotlib.pyplot.ylim(ymax = maxHistData * 1.05)

        if comparePlots:
            for p, pol in enumerate(polList):
                subplots[p][0].set_ylim(ymax = maxYReal)
                subplots[p][1].set_ylim(ymax = maxYImag)
                #matplotlib.pyplot.subplot(numberOfPolarisations, 2, (p2 * 2) + 1)
                #matplotlib.pyplot.ylim(ymax = maxYReal)
                #matplotlib.pyplot.subplot(numberOfPolarisations, 2, (p2 * 2) + 2)
                #matplotlib.pyplot.ylim(ymax = maxYImag)

        fig.canvas.manager.window.after(100, drawDataCallback, comparePlots)

    # start the process
    fig.canvas.manager.window.after(100, drawDataCallback, opts.comparePlots)
    matplotlib.pyplot.show()
    print 'Plot started.'

except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()

print 'Done with all.'
exit_clean()

# end

