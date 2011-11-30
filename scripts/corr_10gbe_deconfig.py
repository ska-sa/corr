#! /usr/bin/env python
"""Stops the tgtap device drivers on all 10GbE interfaces on the ROACH boards.
Author: Jason Manley
Rev
2010-07-28  JRM Port to corr-0.5.0
"""
import corr, time, sys, numpy, os, logging

def exit_fail():
    print 'FAILURE DETECTED. Log entries:\n',c.log_handler.printMessages()
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
    c=corr.corr_functions.Correlator(config_file=config_file,log_level=logging.DEBUG if verbose else logging.INFO,connect=False)
    c.connect()
    print 'done'

    print('\nKilling all 10GbE tgtap drivers...'),
    sys.stdout.flush()
    c.deconfig_roach_10gbe_ports()
    print 'done.'
        

except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()
exit()
