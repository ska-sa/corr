#! /usr/bin/env python
""" 
Check that the pcnt in the f-engines is incrementing correctly.
"""

import corr, sys, logging, time

def exit_fail():
    print 'FAILURE DETECTED. Log entries:\n',lh.printMessages()
    print "Unexpected error:", sys.exc_info()
    try:
        c.disconnect_all()
    except: pass
    exit(1)

def exit_clean():
    try:
        c.disconnect_all()
    except: pass
    exit(0)

if __name__ == '__main__':
    from optparse import OptionParser

    p = OptionParser()
    p.set_usage('%prog [options] [CUSTOM_CONFIG_FILE]')
    p.set_description(__doc__)
    opts, args = p.parse_args(sys.argv[1:])
    if args == []:
        config_file = None
    else:
        config_file = args[0]

lh = corr.log_handlers.DebugLogHandler(100)
try:
    print 'Connecting...',
    c = corr.corr_functions.Correlator(config_file = config_file, log_level = logging.INFO, connect = False, log_handler = lh)
    c.connect()
    print 'done'

    slist = [64, 32, 16, 8, 4, 2, 1, 0.5, 0.25, 0.125]
    wait_time = 1
    slist = [1]

    for s in slist:
        c.config['pcnt_scale_factor'] = c.config['bandwidth'] / c.config['xeng_acc_len'] * s

        print "s(%f) pcnt_scale(%f) bw(%f) xeng_acc_len(%f)" % (s, c.config['pcnt_scale_factor'], c.config['bandwidth'], c.config['xeng_acc_len'])

        print "Getting current system PCNT...",
        pcnta = c.pcnt_current_get()
        print pcnta, "."

        print "Waiting %i seconds..." % wait_time,
        sys.stdout.flush()
        time.sleep(wait_time)
        print "done."

        print "Getting current system PCNT...",
        pcntb = c.pcnt_current_get()
        print pcntb, "."
        
        print "PCNT:         before(%i)\t\tafter_%is(%i)\t\tdiff(%i)" % (pcnta, wait_time, pcntb, pcntb - pcnta)
        timea = c.time_from_pcnt(pcnta)
        timeb = c.time_from_pcnt(pcntb)
        timediff = timeb - timea
        print "PCNT to time: before(%.5fs)\tafter_%is(%.5fs)\tdiff(%.5fs)\terror(%.10fms)" % (timea, wait_time, timeb, timediff, (timediff - wait_time) * 1000.)

except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()
