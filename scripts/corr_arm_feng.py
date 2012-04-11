#! /usr/bin/env python
"""Arms the F engines and resets the cumulative error counters on the X engine.
Rev:
2010-11-26  JRM Resync VACC after arm.
"""
import corr, time, sys, numpy, os, logging

def exit_fail():
    print 'FAILURE DETECTED. Log entries:\n',
    c.log_handler.printMessages()
    print "Unexpected error:", sys.exc_info()
    try:
        c.disconnect_all()
    except: pass
    #raise
    exit()

def exit_clean():
    try:
        c.disconnect_all()
    except: pass
    exit()

if __name__ == '__main__':
    from optparse import OptionParser

    p = OptionParser()
    p.set_usage('%prog CONFIG_FILE')
    p.set_description(__doc__)
    p.add_option('-v', '--verbose', dest='verbose',action='store_true', default=False,
        help='Be verbose about errors.')

    opts, args = p.parse_args(sys.argv[1:])

    if args==[]:
        config_file=None
    else:
        config_file=args[0]
    verbose=opts.verbose

try:    
    print 'Connecting...',
    c = corr.corr_functions.Correlator(config_file=config_file,log_level=logging.DEBUG if verbose else logging.INFO, connect=False)
    c.connect()
    print 'done'

    print ''' Syncing the F engines...''',
    sys.stdout.flush()
    trig_time = c.arm()
    print 'Armed. Expect trigg at %s local (%s UTC).' % (time.strftime('%H:%M:%S', time.localtime(trig_time)), time.strftime('%H:%M:%S', time.gmtime(trig_time))),
    print 'SPEAD packet sent.'

    print('Resyncing VACCs...'),
    sys.stdout.flush()
    c.vacc_sync()
    print 'done.'

    print('Resetting error counters...'),
    sys.stdout.flush()
    c.rst_status_and_count()
    print 'done.'

except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()
exit()
