#! /usr/bin/env python
"""Configures CASPER correlator Fengine's Fringe rotate and delay compensation cores. 
Author: Jason Manley
Revs:
2010-11-20  JRM First release """
import corr, numpy,sys,os,time,logging

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
    p.set_usage('%prog [options] CONFIG_FILE')
    p.set_description(__doc__)
    p.add_option('-a', '--ant', dest = 'ant_str', action = 'store', 
        help = 'Specify the antenna and pol. For example, 3x will give pol x for antenna three.')
    p.add_option('-f', '--fringe_rate', dest='fringe_rate', type='float', default=0,
        help='''Set the fringe rate in cycles per second (Hz). Defaults to zero.''')
    p.add_option('-o', '--fringe_offset', dest='fringe_offset', type='float', default=0,
        help='''Set the fringe offset in degrees. Defaults to zero''')
    p.add_option('-d', '--delay', dest='delay', type='float', default=0,
        help='''Set the delay in seconds. Defaults to zero.''')
    p.add_option('-r', '--delay_rate', dest='delay_rate', type='float', default=0,
        help='''Set the delay rate.  Unitless; eg. seconds per second. Defaults to zero.''')
    p.add_option('-t', '--ld_time', dest='ld_time', type='float', default=-1,
        help='''Load time in seconds since the unix epoch. NOTE: SYSTEM TIME MUST BE ACCURATE! If not specified, load ASAP.''')
    p.add_option('-v', '--verbose', dest = 'verbose', action = 'store_true', 
        help = 'Be verbose about errors.')

    opts, args = p.parse_args(sys.argv[1:])

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

    ant_str=opts.ant_str
    if not ant_str in c.config._get_ant_mapping_list():
        raise RuntimeError("Bad input specified.") 

    if opts.ld_time <0: trig_time = time.time()+0.1
    else: trig_time = opts.ld_time

    print "Setting input %s's delay to %es + %es/s with a fringe of %e + %eHz at %s local (%s UTC).... "%(
        ant_str,opts.delay,opts.delay_rate,opts.fringe_offset,opts.fringe_rate,
        time.strftime('%H:%M:%S',time.localtime(trig_time)),time.strftime('%H:%M:%S',time.gmtime(trig_time))),
    act=c.fr_delay_set(ant_str=ant_str,
            delay=opts.delay,
            delay_rate=opts.delay_rate, 
            fringe_phase=opts.fringe_offset,
            fringe_rate=opts.fringe_rate)
    print 'ok.'

    print 'Closest we could get: '
    print '===================== '
    print 'Actual fringe offset: %15.10e'%act['act_fringe_offset']
    print 'Actual fringe rate:   %15.10e'%act['act_fringe_rate']
    print 'Actual delay:         %15.10e'%act['act_delay']
    print 'Actual delay rate:    %15.10e'%act['act_delay_rate']

except KeyboardInterrupt:
    exit_clean()
except:
    exit_fail()

exit_clean()

