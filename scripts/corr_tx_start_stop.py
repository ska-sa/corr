#! /usr/bin/env python
"""
Starts UDP packet output on the X engine. Does not do any configuration of the output cores.

Author: Jason Manley\n
Revisions:\n
2010-07-29 PVP Cleanup as part of the move to ROACH F-Engines.\n
2009------ JRM Initial revision.\n
"""
import corr, time, sys, numpy, os, logging

def exit_fail():
    #print 'FAILURE DETECTED. Log entries:\n',c.log_handler.printMessages()
    #print "Unexpected error:", sys.exc_info()
    #try:
    #    c.disconnect_all()
    #except: pass
    if verbose:
        raise
    exit()

def exit_clean():
    #try:
    #    c.disconnect_all()
    #except: pass
    exit()


if __name__ == '__main__':
    from optparse import OptionParser

    p = OptionParser()
    p.set_usage('%prog [options] CONFIG_FILE')
    p.add_option('', '--start', dest='txStart', action='store_true', help='Start UDP packet transmission from the X-engines.')
    p.add_option('', '--stop', dest='txStop', action='store_true', help='Stop UDP packet transmission from the X-engines.')
    p.add_option('-v', '--verbose', dest='verbose',action='store_true', default=False, help='Be verbose about stuff.')
    p.set_description(__doc__)
    opts, args = p.parse_args(sys.argv[1:])

    if (opts.txStart and opts.txStop):
        print 'Epic fail! --stop or --start, not both.'
        exit()

    if not (opts.txStart or opts.txStop):
        print 'Epic fail! --stop or --start.'
        exit()

    if args==[]:
        config_file=None
    else:
        config_file=args[0]
    verbose=opts.verbose


try:
    print 'Connecting...',
    c=corr.corr_functions.Correlator(config_file=config_file,log_level=(logging.DEBUG if verbose else logging.INFO),connect=False)
    c.connect()
    print 'done'

    print "Current settings:"
    regValues = c.xeng_ctrl_get_all()
    for fn,value in enumerate(regValues):
        print "\t" + c.xsrvs[fn] + ": tx " + ("enabled" if value['gbe_out_enable'] else "disabled")

    if opts.txStart:
        print "Sending meta data to %s:%i."%(c.config['rx_meta_ip_str'],c.config['rx_udp_port'])
         
        print ''' Issuing data descriptors...''',
        sys.stdout.flush()
        c.spead_data_descriptor_issue()
        print 'SPEAD packet sent.'
        
        print ''' Issuing static metadata...''',
        sys.stdout.flush()
        c.spead_static_meta_issue()
        print 'SPEAD packet sent.'
        
        print ''' Issuing timing metadata...''',
        sys.stdout.flush()
        c.spead_time_meta_issue()
        print 'SPEAD packet sent.'
        
        print ''' Issuing eq metadata...''',
        sys.stdout.flush()
        c.spead_eq_meta_issue()
        print 'SPEAD packet sent.'

        print 'Starting TX...',
        sys.stdout.flush()
        c.enable_udp_output()
        print 'done.'

    if opts.txStop:
        print 'Stopping TX...',
        sys.stdout.flush()
        c.disable_udp_output()
        print 'done.'

    print "Now:"
    regValues = c.xeng_ctrl_get_all()
    for fn,value in enumerate(regValues):
        print "\t" + c.xsrvs[fn] + ": tx " + ("enabled" if value['gbe_out_enable'] else "disabled")

except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()
exit()
