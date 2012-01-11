#! /usr/bin/env python
"""
Reads the error counters on the correlator Xengines and reports such things as accumulated XAUI and packet errors.
\n\n
Revisions:
2010-12-11  JRM Added sync_val to lookup
                added fast scroll ability
                added clear error ability
2010-10-26  PVP Use ncurses via class scroll in scroll.py to allow scrolling around on-screen data
2010-07-22  JRM Ported for corr-0.5.5
2009-12-01  JRM Layout changes, check for loopback sync
2009/11/30  JRM Added support for gbe_rx_err_cnt for rev322e onwards.
2009/07/16  JRM Updated for x engine rev 322 with KATCP.

Todo:
print errors in RED.
"""
import corr, time, sys,struct,logging, curses

lookup = {'adc_overrange': '[ADC OVERRANGE]',
          'ct_error': '[CORNER-TURNER ERROR]',
          'fft_overrange': '[FFT OVERFLOW]',
          'sync_val': 'Sync offset in ADC clock cycles.',
          'quant_overrange': 'Quantiser overrange.',
          'xaui_lnkdn': '[XAUI LINK DOWN]',
          'clk_err': '[SAMPLE CLOCK ERROR]',
          'xaui_over': '[XAUI TX OVERFLOW]'}

ignore = ['sync_val']

def exit_fail():
    print 'FAILURE DETECTED. Log entries:\n',lh.printMessages()
    print "Unexpected error:", sys.exc_info()
    try:
        scroller.screenTeardown()
        c.disconnect_all()        
    except: pass
    if verbose: raise
    exit()

def exit_clean():
    try:
        scroller.screenTeardown()
        c.disconnect_all()        
    except: pass
    exit()

if __name__ == '__main__':
    from optparse import OptionParser

    p = OptionParser()
    p.set_usage('%prog [options] CONFIG_FILE')
    p.set_description(__doc__)
    p.add_option('-c', '--clk_check', dest='clk_check',action='store_true', default=False,
        help='Perform clock integrity checks.')
    p.add_option('-v', '--verbose', dest='verbose',action='store_true', default=False,
        help='Log verbosely.')
    opts, args = p.parse_args(sys.argv[1:])
    if args == []:
        config_file = None
    else:
        config_file = args[0]
    verbose = opts.verbose
lh = corr.log_handlers.DebugLogHandler(35)
try:    
    print 'Connecting...',
    c = corr.corr_functions.Correlator(config_file = config_file, log_level = logging.DEBUG if verbose else logging.INFO, connect = False, log_handler = lh)
    c.connect()
    print 'done'

    scroller = None
    screenData = []
    # set up the curses scroll screen
    scroller = corr.scroll.Scroll()
    scroller.screenSetup()
    scroller.setInstructionString("A toggles auto-clear, C to clear once.")
    scroller.clearScreen()
    scroller.drawString('Connecting...', refresh = True)
    autoClear = False
    clearOnce = False
    scroller.drawString(' done.\n', refresh = True) 
    # get FPGA data
    servers = c.fsrvs
    n_ants = c.config['n_ants']
    start_t = time.time()
    if opts.clk_check:
        clk_check = c.feng_clks_get()
        scroller.drawString('Estimating clock frequencies for connected F engines...\n', refresh = True)
        sys.stdout.flush()
        for fn,feng in enumerate(c.fsrvs):
            scroller.drawString('\t %s (%i MHz)\n' % (feng,clk_check[fn]), refresh = True)
        scroller.drawString('F engine clock integrity: ', refresh = True)
        pps_check = c.check_feng_clks()
        scroller.drawString('%s\n' % {True : 'Pass', False: 'FAIL!'}[pps_check], refresh = True)
        if not pps_check:
            scroller.drawString(c.check_feng_clk_freq(verbose = True) + '\n', refresh = True)
    time.sleep(2)

    # main program loop
    lastUpdate = time.time() - 3
    while True:
        # get key presses from ncurses
        keyPress = scroller.processKeyPress()
        if keyPress[0] > 0:
            if (keyPress[1] == 'a') or (keyPress[1] == 'A'):
                autoClear = not autoClear
            elif (keyPress[1] == 'c') or (keyPress[1] == 'C'):
                clearOnce = True
            scroller.drawScreen(screenData)

        if (time.time() > (lastUpdate + 1)): # or gotNewKey:
            screenData = []
            #lineattrs  = []

            mcnts = c.mcnt_current_get()
            status = c.feng_status_get_all()
            uptime = c.feng_uptime()
            fft_shift = c.fft_shift_get_all()
            
            if c.config['adc_type'] == 'katadc':
                rf_status = c.rf_status_get_all()
            if autoClear or clearOnce:
                c.rst_fstatus()
                clearOnce = False
            for in_n, ant_str in enumerate(c.config._get_ant_mapping_list()):
                ffpga_n, xfpga_n, fxaui_n, xxaui_n, feng_input = c.get_ant_str_location(ant_str)
                screenData.append('  Input %s (%s input %i, mcnt %i):' % (ant_str,c.fsrvs[ffpga_n],feng_input, mcnts[ffpga_n]))
                #lineattrs.append(curses.A_UNDERLINE)
                if c.config['adc_type'] == 'katadc' :
                    screenData.append("    RF %8s:      gain:  %5.1f dB" % ({True: 'Enabled', False: 'Disabled'}[rf_status[ant_str][0]],rf_status[ant_str][1]))
                    #lineattrs.append(curses.A_NORMAL)
                #screenData.append('    FFT shift pattern:       0x%06x' % fft_shift[ant_str])
                #lineattrs.append(curses.A_NORMAL)
                printString = '    Cumulative errors: '
                brd_err = False
                for item, error in status[ant_str].items():
                    if (error == True) and not (item in ignore): 
                        try:
                            printString += lookup[item]
                            if lookup[item][0]=='[': brd_err = True
                        except KeyError: printString += item
                        printString += ', '
                screenData.append(printString)
                #lineattrs.append(curses.A_STANDOUT) if brd_err == True else lineattrs.append(curses.A_NORMAL)
            screenData.append('')
            #lineattrs.append(curses.A_NORMAL)

            screenData.append('Time: %i seconds' % (time.time() - start_t))
            #lineattrs.append(curses.A_NORMAL)
            screenData.append("Auto-clear ON." if autoClear else "Auto-clear OFF.")
            #lineattrs.append(curses.A_NORMAL)
            scroller.drawScreen(screenData)#, lineattrs)
            lastUpdate = time.time()

except KeyboardInterrupt:
        exit_clean()
except: 
        exit_fail()

exit_clean()

