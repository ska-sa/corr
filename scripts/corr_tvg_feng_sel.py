#! /usr/bin/env python
"""Selects TVGs thoughout the correlator.\n
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

if  __name__ == '__main__':
    from optparse import OptionParser

    p = OptionParser()
    p.set_usage(__file__ + ' [options] CONFIG_FILE')
    p.set_description(__doc__)
    # the list of tvgs below
    # F-engine
    p.add_option('-e', '--enable_tvg',  dest = 'tvg_enable',    action = 'store', default = -1, help = 'Global enable the TVGs.')
    p.add_option('-f', '--fd_fs',       dest = 'tvg_fdfs',      action = 'store', default = -1, help = 'FD, FS TVG.')
    p.add_option('-p', '--packetiser',  dest = 'tvg_packetiser',action = 'store', default = -1, help = 'Packetiser TVG.')
    p.add_option('-c', '--pre_ct',      dest = 'tvg_ct',        action = 'store', default = -1, help = 'Pre-CT TVG. Generates a counter so the data for both pols combined forms a 16-bit counter representing the freq channel number.')
    p.add_option('-v', '--verbose', dest='verbose',action='store_true', default=False,
        help='Be verbose about errors.')

    # X-engine
    #p.add_option('-', '--',   dest = 'tvg_', action = 'store', default = 0, help = '')
    opts, args = p.parse_args(sys.argv[1:])

    if args==[]:
        config_file=None
    else:
        config_file=args[0]
    verbose=opts.verbose

try:
    raise RuntimeError('This script is farked. Don''t use it.')

    print 'Connecting...',
    c=corr.corr_functions.Correlator(config_file=config_file,log_level=logging.DEBUG if verbose else logging.INFO,connect=False)
    c.connect()
    print 'done'

    print 'F-engine TVGs:'
    kwargs = {}

    if opts.tvg_enable == 1:
        print "\tGlobal TVG enable ON"
        kwargs["tvg_en"] = True
    elif opts.tvg_enable == 0:
        print "\tGlobal TVG enable OFF"
        kwargs["tvg_en"] = False
    
    if opts.tvg_fdfs == 1:
        print "\tEnabling FD,FS TVG"
        kwargs["tvgsel_fdfs"] = True
    elif opts.tvg_fdfs == 0:
        print "\tDisabling FD,FS TVG"
        kwargs["tvgsel_fdfs"] = False

    if opts.tvg_packetiser == 1:
        print "\tEnabling packetiser TVG"
        kwargs["tvg_pkt_sel"] = True
    elif opts.tvg_packetiser == 0:
        print "\tDisabling packetiser TVG"
        kwargs["tvg_pkt_sel"] = False

    if opts.tvg_ct == 1:
        print "\tEnabling CT TVG"
        kwargs["tvg_ct_sel"] = True
    elif opts.tvg_ct == 0:
        print "\tDisabling CT TVG"
        kwargs["tvg_ct_sel"] = False

    c.feng_ctrl_set_all(**kwargs)
    
    print "Done."

    #print '\nX engine TVGs:'
    #if opts.xeng:
    #    print('\tEnabling Xeng TVG...'),
    #    c.tvg_xeng_sel(mode=1)
    #    print 'done Xengine TVG.'
    #elif opts.vacc:
    #    print('\tEnabling VACC TVG...')
    #    print 'done VACC TVG.'
    #print 'done all X engine TVGs.'

except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()

exit_clean()

# end

