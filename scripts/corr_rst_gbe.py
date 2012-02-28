#! /usr/bin/env python
"""
Resets the 10GbE cores on all X engines through fabric rst port toggle.
"""
import corr, time, sys, numpy, os, logging

def exit_fail():
    print 'FAILURE DETECTED. Log entries:\n',
    c.log_handler.printMessages()
    try:
        c.disconnect_all()
    except: pass
    time.sleep(1)
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

    opts, args = p.parse_args(sys.argv[1:])

    if args == []:
        config_file = None
    else:
        config_file = args[0]
    #verbose=opts.verbose
    verbose = False

try:    
    print 'Connecting...',
    c = corr.corr_functions.Correlator(config_file = config_file, log_level = logging.DEBUG if verbose else logging.INFO, connect = False)
    c.connect()
    print 'done'

    print('\nResetting GBE cores...'),
    sys.stdout.flush()

    #DO NOT RESET THE 10GBE CORES SYNCHRONOUSLY!
    if c.config['feng_out_type']=='10gbe':
        c.feng_ctrl_set_all(gbe_enable = False, gbe_rst = False)
        c.feng_ctrl_set_all(gbe_enable = False, gbe_rst = True)
        c.feng_ctrl_set_all(gbe_enable = False, gbe_rst = False)
        c.feng_ctrl_set_all(gbe_enable = True,  gbe_rst = False)

    c.xeng_ctrl_set_all(gbe_enable = False, gbe_rst = False) 
    c.xeng_ctrl_set_all(gbe_enable = False, gbe_rst = True)
    c.xeng_ctrl_set_all(gbe_enable = False, gbe_rst = False)
    c.xeng_ctrl_set_all(gbe_enable = True,  gbe_rst = False)

    print 'done.'

except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()
exit()
