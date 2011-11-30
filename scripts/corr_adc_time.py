#!/usr/bin/env python

'''
Plots histogram, time-domain and spectral snapshot of the ADC values in realtime from a specified antenna and pol.

'''
'''
Revisions:
2011-04-04  JRM Overhaul. Merge with RFI system's time domain to include histogram and spectrum plot.
2011-03-xx  JRM Misc modifications, feature additions etc
2011-02-24  JRM Port to RFI system
2010-12-11: JRM Add printout of number of bits toggling in ADC.
                Add warning for non-8bit ADCs.
2010-08-05: JRM Mods to support variable snap block length.
1.1 PVP Initial.\n

'''

#TODO: Add duty-cycle measurement support.
#TODO: Add trigger count support.

import matplotlib
matplotlib.use('TkAgg')
import time, corr, numpy, struct, sys, logging, pylab

# what format are the snap names and how many are there per antenna
snapName = 'snap_adc'
# what is the bram name inside the snap block
bramName = 'bram'

def exit_fail():
    print 'FAILURE DETECTED. Log entries:\n',
    try:
        f.flush()
        if filename != None:
            f.close()
        r.lh.printMessages()
        r.fpga.stop()
    except:
        pass
    if verbose:
        raise
    exit()

def exit_clean():
    try:
        print "Closing file."
        f.flush()
        f.close()
        r.fpga.stop()
    except:
        pass
    exit()

# callback function to draw the data for all the required polarisations
def drawDataCallback(n_samples,indep,trig_level):
    unpackedData, timestamp,status = getUnpackedData(trig_level=trig_level)
    filewrite(unpackedData,timestamp,status)

    subplots[0].cla()
    subplots[0].set_xticks(range(-130, 131, 20))
    histData, bins, patches = subplots[0].hist(unpackedData, bins = 256, range = (-128,128))
    if status['adc_overrange'] or status['adc_disabled']:
        subplots[0].set_title('Histogram as at %s'%(time.ctime(timestamp)),bbox=dict(facecolor='red', alpha=0.5))
    else:
        subplots[0].set_title('Histogram as at %s for input %s'%(time.ctime(timestamp),ant_str))
    subplots[0].set_ylabel('Counts')
    subplots[0].set_xlabel('ADC sample bins.')
    matplotlib.pyplot.ylim(ymax = (max(histData) * 1.05))            

    cal_data=c.calibrate_adc_snapshot(ant_str,raw_data=unpackedData,n_chans=n_chans)
    calData=cal_data['adc_v']*1000
    max_lev =numpy.max(numpy.abs(calData))
    abs_levs=numpy.abs(unpackedData)
    max_adc = numpy.max(abs_levs)
    trigs = numpy.ma.flatnotmasked_edges(numpy.ma.masked_less_equal(abs_levs,(trig_level-1)))
    #print trigs
    if (trigs == None or trigs[0] ==0) and trig_level>0 and (max_adc)<trig_level: 
        print('ERROR: we asked for a trigger level of %i and the hardware reported success, but the maximum level in the returned data was only %i. Got %i samples.'%(trig_level,max_adc,len(calData)))

    #if there was no triggering:
    if trigs==None:
        max_pos = numpy.argmax(calData)
    else:
        max_pos = trigs[0]
    
    subplots[1].cla()
    if indep:
        max_pos=(max_pos/2)*2
        t_start =max(0,max_pos-n_samples/2)
        t_stop  =min(len(calData),max_pos+n_samples/2)
        p_data=calData[t_start:t_stop]
        x_range=numpy.arange(t_start-max_pos,t_stop-max_pos)
        #print max_pos,t_start,t_stop,len(x_range)

        subplots[1].plot(x_range[0::2],p_data[0::2])
        subplots[1].plot(x_range[1::2],p_data[1::2])
        subplots[1].set_xlim(-n_samples/4*1.e9/sample_clk,n_samples/4)
    else:
        t_start =max(0,max_pos-n_samples/2)
        t_stop  =min(len(calData),max_pos+n_samples/2)
        p_data  =calData[t_start:t_stop]
        x_range =numpy.arange(t_start-max_pos,t_stop-max_pos)*1.e9/sample_clk
        #print max_pos,t_start,t_stop,len(x_range)

        subplots[1].plot(x_range,p_data)
        subplots[1].set_xlim(-n_samples/2*1.e9/sample_clk,n_samples/2*1.e9/sample_clk)

    if status['adc_overrange'] or status['adc_disabled']:
        subplots[1].set_title('Time-domain (max %4.2fmV)'%(max_lev), bbox=dict(facecolor='red', alpha=0.5))
    else:
        subplots[1].set_title('Time-domain (max %4.2fmV; ADC %i)'%(max_lev,max_adc))
    subplots[1].set_ylim(-max_lev-1,max_lev+1)
    subplots[1].set_ylabel('mV')
    subplots[1].set_xlabel('Time (nanoseconds).')

    subplots[2].cla()

    empty_spec=c.calibrate_adc_snapshot(ant_str,raw_data=unpackedData[0:max_pos-1],n_chans=n_chans)
    emptySpectrum=empty_spec['spectrum_dbm']
    fullSpectrum=cal_data['spectrum_dbm']
    freqs=cal_data['freqs']

    #print 'plotting from %i to %i'%(t_start,max_pos-1)
    pylab.hold(True)
    subplots[2].plot(freqs/1e6,fullSpectrum,label='Signal on')
    pylab.hold(True)
    subplots[2].plot(freqs/1e6,emptySpectrum,label='Quiescent')
    subplots[2].legend()
    subplots[2].set_title('Spectrum of capture (%i samples)'%(len(unpackedData)))
    subplots[2].set_ylabel('Level (dBm)')
    subplots[2].set_xlabel('Frequency (MHz)')
 
    fig.canvas.draw()
    fig.canvas.manager.window.after(100, drawDataCallback, n_samples,indep,trig_level)

# the function that gets data given a required polarisation
def getUnpackedData(trig_level=-1):
    # get the data
    adc_snap_raw = corr.snap.get_adc_snapshots(c,[ant_str],trig_level=trig_level,sync_to_pps=False)[ant_str]
    unpackedBytes = adc_snap_raw['data']
    timestamp=c.time_from_mcnt(adc_snap_raw['timestamp'])
    stat=c.feng_status_get(opts.antAndPol)
    stat.update(c.adc_amplitudes_get(antpols=[ant_str])[ant_str]) 

    print '%s: input level: %5.2f dBm (%5.2f dBm into ADC).'%(time.ctime(timestamp),stat['input_rms_dbm'],stat['adc_rms_dbm']),
    if stat['adc_disabled']: print 'ADC selfprotect due to overrange!',
    if stat['adc_overrange']: print 'ADC is clipping!',
    print ''
    return unpackedBytes, timestamp, stat

def filewrite(adc_data,timestamp,status):
    if filename != None:
        cnt=f['raw_dumps'].shape[0]-1
        print '  Storing entry %i...'%cnt,
        sys.stdout.flush()
        f['raw_dumps'][cnt] = adc_data 
        f['timestamp'][cnt] = timestamp
        f['adc_overrange'][cnt] = status['adc_overrange']
        f['fft_overrange'][cnt] = status['fft_overrange']
        f['adc_shutdown'][cnt] = status['adc_selfprotect']
        f['adc_level'][cnt] = status['adc_rms_dbm']
        for name in ['raw_dumps','timestamp','adc_overrange','fft_overrange','adc_shutdown','adc_level']:
            f[name].resize(cnt+2, axis=0)
        print 'Appended to file.'


if __name__ == '__main__':
    from optparse import OptionParser
    p = OptionParser()
    p.set_usage('%prog [options] [CONFIG_FILE]')
    p.add_option('-v', '--verbose', dest = 'verbose', action = 'store_true',default=False, 
        help = 'Enable debug mode.')
    p.add_option('-i', '--plot_indep', dest = 'plot_indep', action = 'store_true', 
        help = 'Plot interleaved ADC independantly.')
    p.add_option('-f', '--file', dest = 'file', type='string', 
        help = 'Write to H5 file.')
    p.add_option('-t', '--capture_len', dest = 'capture_len', type='int', default = 100, 
        help = 'Plot this many nano-seconds around the trigger point. Default:100')
    #p.add_option('-u', '--units', dest = 'units', type='string', default = 'dBm', 
    #    help = 'Choose the units for y-axis in freq plots. Options include dBuV,dBm. Default:dBm')
    p.add_option('-c', '--n_chans', dest = 'n_chans', type='int', default = 1024, 
        help = 'Number of frequency channels to resolve in software FFT. Default:1024')
    p.add_option('-a', '--antenna', dest = 'antAndPol', action = 'store', help = 'Specify an antenna and pol for which to get ADC histograms. 3x will give pol     x for antenna three. 27y will give pol y for antenna 27.')
    p.add_option('-l', '--trig_level', dest = 'trig_level', type='int', default = 0, 
        help = 'Ask the hardware to wait for a signal with at least this amplitude (in ADC counts) before capturing. Valid range: 0-127. Default:0')
    p.set_description(__doc__)
    opts, args = p.parse_args(sys.argv[1:])
    verbose=opts.verbose
    n_chans=opts.n_chans
    if opts.file: filename=opts.file
    else: filename=None

    if opts.antAndPol == None:
        print 'No antenna given for which to plot data.'
        exit_fail()

    if args==[]:
        config_file=None
    else:
        config_file=args[0]


try:
    # make the correlator object
    print 'Connecting to correlator...',
    c=corr.corr_functions.Correlator(config_file=config_file,log_level=logging.DEBUG if verbose else logging.INFO,connect=False)
    c.connect()
    print 'done.'

    ant_str = opts.antAndPol
    rf_gain     =c.rf_status_get(ant_str)[1]
    trig_scale_factor=c.config['adc_v_scale_factor']*1000.
    sample_clk  =c.config['adc_clk']
    n_samples   =int(opts.capture_len/1.e9*sample_clk)
    trig_level  =opts.trig_level
    bandwidth   =c.config['bandwidth']
    if filename != None:
        import h5py
        print 'Starting file %s.'%filename
        f = h5py.File(filename, mode="w")
        baseline=r.get_adc_snapshot()
        f.create_dataset('raw_dumps',shape=[1,len(baseline)],dtype=numpy.int8,maxshape=[None,len(baseline)])
        f.create_dataset('timestamp',shape=[1],maxshape=[None],dtype=numpy.uint32)
        f.create_dataset('adc_overrange',shape=[1],maxshape=[None],dtype=numpy.bool)
        f.create_dataset('fft_overrange',shape=[1],maxshape=[None],dtype=numpy.bool)
        f.create_dataset('adc_shutdown',shape=[1],maxshape=[None],dtype=numpy.bool)
        f.create_dataset('adc_level',shape=[1],maxshape=[None],dtype=numpy.float)
        f['/'].attrs['bandwidth']=bandwidth
        f['/'].attrs['adc_type']=c.config['adc_type']
        f['/'].attrs['adc_scale_to_mv']=trig_scale_factor
        f['/'].attrs['rf_gain']=rf_gain
        f['/'].attrs['usrlog']=usrlog
        f['/'].attrs['sample_clk']=sample_clk
        f['/'].attrs['trig_level']=trig_level
        f['/'].attrs['ant']=opts.antAndPol

    freqs=numpy.arange(n_chans)*float(bandwidth)/n_chans #channel center freqs in Hz

    print 'Triggering at an ADC level of %i (approx %4.2fmV).'%(trig_level,trig_level*trig_scale_factor)
    print 'Plotting %i samples.'%n_samples

    # set up the figure with a subplot for each polarisation to be plotted
    fig = matplotlib.pyplot.figure()

    # create the subplots
    subplots = []
    for p in range(3):
        subPlot = fig.add_subplot(3, 1, p + 1)
        subplots.append(subPlot)

    # start the process
    print 'Starting plots...'
    fig.subplots_adjust(hspace=0.8)
    fig.canvas.manager.window.after(100, drawDataCallback, n_samples,opts.plot_indep,trig_level)
    matplotlib.pyplot.show()

except KeyboardInterrupt:
    exit_clean()
except:
#    exit_fail()
    raise

print 'Done with all.'
exit_clean()

# end

