#!/usr/bin/python
"""
 Capture utility for a relatively generic packetised correlator data output stream.

 The script performs two primary roles:

 Storage of stream data on disk in hdf5 format. This includes placing meta data into the file as attributes.

 Regeneration of a SPEAD stream suitable for us in the online signal displays. At the moment this is basically
 just an aggregate of the incoming streams from the multiple x engines scaled with n_accumulations (if set)

Author: Simon Ratcliffe
Revs:
2010-11-26  JRM Added command-line option for autoscaling.
"""

import numpy as np, spead, logging, sys, time, h5py, corr

logging.basicConfig(level=logging.WARN)
acc_scale=True

if __name__ == '__main__':
    from optparse import OptionParser
    p = OptionParser()
    p.set_usage('%prog [options] [CUSTOM_CONFIG_FILE]')
    p.set_description(__doc__)
    p.add_option('-a', '--disable_autoscale', dest='acc_scale',action='store_false', default=True,
        help='Do not autoscale the data by dividing down by the number of accumulations.  Default: Scale back by n_accs.')
    p.add_option('-v', '--verbose', dest='verbose',action='store_true', default=False, 
        help='Be verbose about errors.')
    opts, args = p.parse_args(sys.argv[1:])

    if args==[]:
        config_file=None
    else:
        config_file=args[0]
    acc_scale=opts.acc_scale  
    verbose=opts.verbose  

print 'Parsing config file...',
sys.stdout.flush()
c=corr.corr_functions.Correlator(config_file=config_file,log_level=logging.DEBUG if verbose else logging.WARN, connect=False)
config=c.config
print 'done.'

data_port = config['rx_udp_port']
sd_ip = config['sig_disp_ip_str']
sd_port = config['sig_disp_port']
mode=config['xeng_format']

filename=str(time.time()) + '.corr.h5'

print 'Initalising SPEAD transports for %s data...'%mode
print "Data reception on port",data_port
print "Sending Signal Display data to %s:%i."%(sd_ip,sd_port)
print "Storing to file %s"%filename

crx=corr.rx.CorrRx(mode=mode,data_port=data_port,sd_ip=sd_ip,sd_port=sd_port,acc_scale=acc_scale,filename=filename,log_level=logging.DEBUG if verbose else logging.INFO)
try:
    crx.daemon=True
    crx.start()
    while(crx.isAlive()):
        time.sleep(0.1)
    print 'RX process ended.'
    crx.join()
except KeyboardInterrupt:
    print 'Stopping...'
