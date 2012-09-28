#! /usr/bin/env python
"""
Reads the error counters on the correlator Xengines and reports such things as accumulated XAUI and packet errors.
\n\n
Revisions:
2010-12-11  JRM Fix to allow fast scrolling of curses display
2010-11-25  JRM Bugfix to also lookup gbe_tx_cnt if hardware outputs 10Gbe
2010-10-25  PVP Use ncurses via class scroll in scroll.py to allow scrolling around on-screen data
2010-07-22  JRM Ported for corr-0.5.5
2009-12-01  JRM Layout changes, check for loopback sync
2009-11-30  JRM Added support for gbe_rx_err_cnt for rev322e onwards.
2009-07-16  JRM Updated for x engine rev 322 with KATCP.
"""
import corr, time, sys, struct, logging

scroller = None
screenData = []

def exit_fail():
    print 'FAILURE DETECTED. Log entries:\n',lh.printMessages()
    print "Unexpected error:", sys.exc_info()
    try:
        scroller.screenTeardown()
        c.disconnect_all()
    except: pass
    if verbose:
        raise
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
    p.add_option('-v', '--verbose', dest='verbose',action='store_true', default=False,
        help='Be verbose about errors.')

    opts, args = p.parse_args(sys.argv[1:])

    if args==[]:
        config_file=None
    else:
        config_file=args[0]
    verbose=opts.verbose
lh=corr.log_handlers.DebugLogHandler(35)
try:
    print 'Connecting...',
    c=corr.corr_functions.Correlator(config_file=config_file,log_handler=lh,log_level=logging.DEBUG if verbose else logging.INFO,connect=False)
    c.connect()
    print 'done'

    # set up the curses scroll screen
    scroller = corr.scroll.Scroll()
    scroller.screenSetup()
    # get FPGA data
    servers = c.xsrvs
    n_xeng_per_fpga = c.config['x_per_fpga']
    n_xaui_ports_per_fpga = c.config['n_xaui_ports_per_xfpga']
    xeng_acc_len = c.config['xeng_acc_len']
    start_t = time.time()
    # main program loop
    lastUpdate = time.time() - 3
    while True:
        # get key presses from ncurses
        if scroller.processKeyPress()[0] > 0:
            scroller.drawScreen(screenData)

        if (time.time() > (lastUpdate + 1)): # or gotNewKey:
            screenData = []

            if c.config['feng_out_type']=='xaui':
                loopmcnt=[]
                gbemcnt=[]
                try:
                    loopback_ok=c.check_loopback_mcnt() 
                except: 
                    loopback_ok=False
                xaui_errors =  [c.xread_uint_all('xaui_err%i'%(x)) for x in range(n_xaui_ports_per_fpga)]
                xaui_rx_cnt =  [c.xread_uint_all('xaui_cnt%i'%(x)) for x in range(n_xaui_ports_per_fpga)]
                loop_cnt =     [c.xread_uint_all('loop_cnt%i'%x) for x in range(min(n_xaui_ports_per_fpga,n_xeng_per_fpga))]
                loop_err_cnt = [c.xread_uint_all('loop_err_cnt%i'%x) for x in range(min(n_xaui_ports_per_fpga,n_xeng_per_fpga))]
                mcnts =        [c.xread_uint_all('loopback_mux%i_mcnt'%(x)) for x in range(min(n_xaui_ports_per_fpga,n_xeng_per_fpga))]
                sum_xaui_errs = sum([sum(xaui_error_n) for xaui_error_n in xaui_errors])
                for mi,mv in enumerate(mcnts):
                    loopmcnt.append([mv[x]/(2**16) for x,f in enumerate(c.xfpgas)])
                    gbemcnt.append([mv[x]&((2**16)-1) for x,f in enumerate(c.xfpgas)])

            if c.config['feng_out_type']=='xaui' or c.config['out_type']=='10gbe':
                gbe_tx_cnt =[c.xread_uint_all('gbe_tx_cnt%i'%(x)) for x in range(n_xaui_ports_per_fpga)]
                gbe_tx_err =[c.xread_uint_all('gbe_tx_err_cnt%i'%(x)) for x in range(n_xaui_ports_per_fpga)]

            rx_cnt     = [c.xread_uint_all('rx_cnt%i'%(x)) for x in range(min(n_xaui_ports_per_fpga,n_xeng_per_fpga))]
            gbe_rx_cnt = [c.xread_uint_all('gbe_rx_cnt%i'%x) for x in range(min(n_xaui_ports_per_fpga,n_xeng_per_fpga))]
            gbe_rx_err_cnt = [c.xread_uint_all('gbe_rx_err_cnt%i'%x) for x in range(min(n_xaui_ports_per_fpga,n_xeng_per_fpga))]
            rx_err_cnt = [c.xread_uint_all('rx_err_cnt%i'%x) for x in range(min(n_xaui_ports_per_fpga,n_xeng_per_fpga))]

            x_cnt      = [c.xread_uint_all('pkt_reord_cnt%i'%(x)) for x in range(n_xeng_per_fpga)]
            x_miss     = [c.xread_uint_all('pkt_reord_err%i'%(x)) for x in range(n_xeng_per_fpga)]
            last_miss_ant = [c.xread_uint_all('last_missing_ant%i'%(x)) for x in range(n_xeng_per_fpga)]
            
            vacc_cnt   = [c.xread_uint_all('vacc_cnt%i'%x) for x in range(n_xeng_per_fpga)]
            vacc_err_cnt = [c.xread_uint_all('vacc_err_cnt%i'%x) for x in range(n_xeng_per_fpga)]
            vacc_ld_stat = c.vacc_ld_status_get()

            sum_bad_pkts = sum([sum(x_miss_n) for x_miss_n in x_miss])/xeng_acc_len
            sum_spectra = sum([sum(engcnt) for engcnt in x_cnt])

            for fn,srv in enumerate(c.xsrvs):
                screenData.append('  ' + srv)

                if c.config['feng_out_type']=='xaui':
                    for x in range(n_xaui_ports_per_fpga):
                        screenData.append('\tXAUI%i         RX cnt: %10i    Errors: %10i' % (x,xaui_rx_cnt[x][fn],xaui_errors[x][fn]))

                for x in range(min(n_xaui_ports_per_fpga,n_xeng_per_fpga)):
                    screenData.append('\t10GbE%i        TX cnt: %10i    Errors: %10i' % (x,gbe_tx_cnt[x][fn],gbe_tx_err[x][fn]))
                    screenData.append("\t10GbE%i        RX cnt: %10i    Errors: %10i" % (x,gbe_rx_cnt[x][fn],gbe_rx_err_cnt[x][fn]))
                    if c.config['feng_out_type']=='xaui':
                        screenData.append('\tLoopback%i        cnt: %10i    Errors: %10i' % (x,loop_cnt[x][fn],loop_err_cnt[x][fn]))
                        screenData.append("\tLoopback_mux%i    cnt: %10i    Errors: %10i" % (x,rx_cnt[x][fn],rx_err_cnt[x][fn]))
                        screenData.append('\t  Loopback%i     mcnt: %6i' % (x,loopmcnt[x][fn]))
                        screenData.append('\t  GBE%i          mcnt: %6i' % (x,gbemcnt[x][fn]))

                    
                for x in range(n_xeng_per_fpga):
                    printString = '\tX engine%i Spectr cnt: %10i    Errors: %10.2f' % (x,x_cnt[x][fn],float(x_miss[x][fn])/float(xeng_acc_len))
                    if x_miss[x][fn] > 0:
                        printString = printString + 'Last missing antenna: %i' % last_miss_ant[x][fn]
                    screenData.append(printString)
                    screenData.append("\tVector Accum%i    cnt: %10i    Errors: %10i" % (x,vacc_cnt[x][fn],vacc_err_cnt[x][fn]))
                    screenData.append("\t             arm_cnt: %10i  load_cnt: %10i" % (vacc_ld_stat[srv]['arm_cnt%i'%x],vacc_ld_stat[srv]['ld_cnt%i'%x]))

                screenData.append('')

            if c.config['feng_out_type']=='xaui':
                screenData.append('Total bad XAUI packets received: %i' % sum_xaui_errs)
                screenData.append('Loopback muxes all syncd: %i' % loopback_ok)

            screenData.append('Total number of spectra processed: %i' % sum_spectra)
            screenData.append('Total bad X engine data: %i packets' % sum_bad_pkts)
            screenData.append('Time: %i' %(time.time() - start_t))
            scroller.drawScreen(screenData)
            lastUpdate = time.time()

except KeyboardInterrupt:
        exit_clean()
except: 
        exit_fail()

exit_clean()

