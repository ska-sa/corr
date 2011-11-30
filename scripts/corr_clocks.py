#! /usr/bin/env python
""" 
Script for checking the approximate clock rate of correlator FPGAs.

Author: Jason Manley\n
Revisions:\n
2010-07-28 PVP Mods as part of the move to ROACH F-Engines. Get F-engine or X-engine clocks or both.\n
2009-07-01 JRM Initial revision.\n
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
    p.set_usage('%prog [options] CONFIG FILE')
    p.add_option('-f', '--fengine', dest='fengine', action='store_true', help='Get F-engine clocks.')
    p.add_option('-x', '--xengine', dest='xengine', action='store_true', help='Get X-engine clocks.')
    p.add_option('-v', '--verbose', dest='verbose', action='store_true', default=False, help='Be verbose about stuff.')
    p.set_description(__doc__)
    opts, args = p.parse_args(sys.argv[1:])

    if not (opts.fengine or opts.xengine):
        print 'Either -f or -x (or both) must be supplied.'
        exit()

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

    print('\nCalculating all clocks...'),
    sys.stdout.flush()
    xclks = []
    fclks = []
    if opts.xengine:
        xclks = c.xeng_clks_get()
    if opts.fengine:
        fclks = c.feng_clks_get()
    print 'done.'

    if opts.xengine:
        for s, server in enumerate(c.xsrvs):
            print 'X:' + server + ': %i MHz'%xclks[s]
    if opts.fengine:
        for s, server in enumerate(c.fsrvs):
            print 'F:' + server + ': %i MHz'%fclks[s]

    #lh.printMessages()

except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()

exit_clean()


