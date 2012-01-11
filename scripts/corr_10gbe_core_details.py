#!/usr/bin/env python

'''
Prints the details of the 10GbE cores on all the X engines.
Assumes the correlator is already initialsed and running etc.
Revisions
2010-07-23  JRM Mods to use corr-0.5.0
2009-12-01  JRM uses katcp_wrapper function now.
2009/11/12  JRM after discussion with Dave.
'''
import corr, time, numpy, struct, sys, logging


def exit_fail():
    print 'FAILURE DETECTED. Log entries:\n',c.log_handler.printMessages()
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
    p.set_usage('%prog [options] CONFIG_FILE')
    p.set_description(__doc__)
    p.add_option('-v', '--verbose', dest='verbose', action='store_true',
        help='Be Verbose; print raw packet contents of CPU contents.')   
    p.add_option('-a', '--arp', dest='arp', action='store_true',
        help='Print the ARP table.')

    opts, args = p.parse_args(sys.argv[1:])
    gbe_device='gbe'

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

    #assemble struct for header stuff...
    #0x00 - 0x07: My MAC address
    #0x08 - 0x0b: Not used
    #0x0c - 0x0f: Gateway addr
    #0x10 - 0x13: my IP addr
    #0x14 - 0x17: Not assigned
    #0x18 - 0x1b: Buffer sizes
    #0x1c - 0x1f: Not assigned
    #0x20       : soft reset (bit 0)
    #0x21       : fabric enable (bit 0)
    #0x22 - 0x23: fabric port 
    
    #0x24 - 0x27: XAUI status (bit 2,3,4,5=lane sync, bit6=chan_bond)
    #0x28 - 0x2b: PHY config
    #0x28       : RX_eq_mix
    #0x29       : RX_eq_pol
    #0x2a       : TX_preemph
    #0x2b       : TX_diff_ctrl

    #0x1000     : CPU TX buffer
    #0x2000     : CPU RX buffer
    #0x3000     : ARP tables start

    if c.config['feng_out_type']=='10gbe':
        for f,fpga in enumerate(c.ffpgas):
            print '\n\n================================'
            for core in range(c.config['n_xaui_ports_per_ffpga']):
                device = '%s%i'%(gbe_device,core)
                print 'F engine', c.fsrvs[f], 'port', core
                fpga.print_10gbe_core_details(device,arp=opts.arp,cpu=opts.verbose) 
            print '================================'

    for f,fpga in enumerate(c.xfpgas):
        print '\n\n================================'
        for core in range(c.config['n_xaui_ports_per_xfpga']):
            device = '%s%i'%(gbe_device,core)
            print 'X engine', c.xsrvs[f], 'port', core
            fpga.print_10gbe_core_details(device,arp=opts.arp,cpu=opts.verbose) 
        print '================================'



except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()

exit_clean()


