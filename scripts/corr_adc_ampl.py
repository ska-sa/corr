#!/usr/bin/env python

'''
Reads the values of the RMS amplitude accumulators on the ibob through the X engine's XAUI connection.\n

Revisions:
2011-01-04  JRM Moved scroller screen teardown into try statement so that it doesn't clobber real error messages in the event that it wasn't instantiated in the first place.
2010-12-11  JRM Removed bit estimate printing.
                ADC overrange now just shows flag, does not cover amplitude text.
                ncurses scroller fix to allow fast scrolling of screen.
1.32 JRM swapped corr.rst_cnt for corr.rst_fstat and swapped column for RMS levels in dB.
1.31 PVP Changed to accomodate change to corr_functions.adc_amplitudes_get() function - key in return dict changed from rms to rms_raw
1.30 PVP Change to ncurses interface with ability to clear error statuses using corr.rst_cnt 
1.21 PVP Fix filename in OptionParser section.
1.20 JRM Support any number of antennas together with F engine 305 and X engine rev 322 and later.\n
1.10 JRM Requires F engine rev 302 or later and X engine rev 308 or later.\n

'''
import corr, time, numpy, struct, sys, logging,curses

def exit_fail():
    print 'FAILURE DETECTED. Log entries:\n', c.log_handler.printMessages()
    print "Unexpected error:", sys.exc_info()
    try:
        #scroller.screenTeardown()
        c.disconnect_all()
    except: pass
    raise
    exit()

def exit_clean():
    scroller.screenTeardown()
    try:
        c.disconnect_all()
    except: pass
    exit()

if __name__ == '__main__':
    from optparse import OptionParser
    p = OptionParser()
    p.set_usage(__file__ + ' [options] CONFIG FILE')
    p.add_option('-v', '--verbose', dest='verbose', action='store_true', help='Print raw output.')
    p.set_description(__doc__)
    opts, args = p.parse_args(sys.argv[1:])

    if args==[]:
        config_file=None
    else:
        config_file=args[0]
    verbose=opts.verbose

try:    
    print 'Connecting...',
    c=corr.corr_functions.Correlator(config_file=config_file,log_level=logging.DEBUG if verbose else logging.INFO, connect=False)
    c.connect()
    print 'done'

    time.sleep(1)
    # set up the curses scroll screen
    scroller = corr.scroll.Scroll()
    scroller.screenSetup()
    scroller.setInstructionString("A toggles auto-clear, C to clear once.")
    # main program loop
    lastUpdate = time.time() - 3
    autoClear = False
    clearOnce = False
    screenData = []
    while(True):
        # get key presses from ncurses
        keyPress = scroller.processKeyPress()
        if keyPress[0] > 0:
            if (keyPress[1] == 'a') or (keyPress[1] == 'A'):
                autoClear = not autoClear
            elif (keyPress[1] == 'c') or (keyPress[1] == 'C'):
                clearOnce = True
            scroller.drawScreen(screenData)

        if (time.time() > (lastUpdate + 1)):
            screenData = []
            lineattrs=[]
            amps = c.adc_amplitudes_get()
            stats = c.feng_status_get_all()
            if autoClear or clearOnce:
                c.rst_fstatus()
                clearOnce = False
            screenData.append('IBOB: ADC0 is furthest from power port, ADC1 is closest to power port.')
            screenData.append('ROACH: ADC0 is right, ADC1 is left (when viewed from front).')
            screenData.append('ADC input amplitudes averaged %i times.' % c.config['adc_levels_acc_len'])
            screenData.append('------------------------------------------------')
            for line in range(4):
                lineattrs.append(curses.A_NORMAL)
            for i in range(c.config['n_inputs']):
                error=False
                ant_str=c.config.map_input_to_ant(i)
                ffpga_n,xfpga_n,fxaui_n,xxaui_n,feng_input = c.get_input_location(c.config.map_ant_to_input(ant_str))
                displayString = 'Ant %s (%s in%i): ' % (ant_str, c.fsrvs[ffpga_n], feng_input)
                if c.config['adc_type'] == 'katadc':
                    displayString += ' Board input of %6.2f dBm with preamp of %5.1fdB = %6.2fdBm into ADC.' % (
                        amps[ant_str]['input_rms_dbm'],amps[ant_str]['analogue_gain'],amps[ant_str]['adc_rms_dbm'])
                else:
                    displayString += ' %.3f' % (amps[ant_str]['rms_raw'])
                if stats[ant_str]['adc_overrange']:
                    displayString += ' ADC OVERRANGE!'
                    error=True
                if stats[ant_str]['adc_disabled']:
                    displayString += ' ADC is disabled!'
                    error=True
                if amps[ant_str]['low_level_warn']:
                    displayString += ' ADC input low; readings inaccurate!'
                    error=True
                screenData.append(displayString)
                #lineattrs.append(curses.A_BOLD if error==True else curses.A_NORMAL)
                lineattrs.append(curses.A_STANDOUT if error==True else curses.A_NORMAL)
                #if error==True:
                #    screenData.append(corr.termcolors.colorize(displayString,fg='red'))
                #else:
                #    screenData.append(corr.termcolors.colorize(displayString,fg='green'))
                #lineattrs.append(curses.COLOR_RED if error==True else curses.COLOR_GREEN)
            screenData.append(""); lineattrs.append(curses.A_NORMAL)
            if autoClear: screenData.append("Auto-clear ON.")
            else: screenData.append("Auto-clear OFF.")
            lineattrs.append(curses.COLOR_WHITE)
            scroller.drawScreen(screenData,lineattrs)
            #scroller.drawScreen(screenData)
            lastUpdate = time.time()
            time.sleep(0.1)

except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()

print 'Done with all'
exit_clean()

# end

