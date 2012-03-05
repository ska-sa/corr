#! /usr/bin/env python
""" 
Reset ALL THE THINGS!
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

    print 'Pulsing reset line...',
    c.feng_ctrl_set_all(sys_rst = 'pulse')
    print 'done.'

except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()
