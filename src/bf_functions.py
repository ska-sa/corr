# /usr/bin/env python
""" 
Selection of commonly-used beamformer control functions.

Author: Jason Manley, Andrew Martens
"""
"""
Revisions:
2012-10-02 JRM Initial
2013-02-10 AM basic boresight
2013-02-11 AM basic SPEAD
2013-02-21 AM flexible bandwidth
\n"""

import corr, time, sys, numpy, os, logging, katcp, struct, construct, socket, spead

class fbf:
    """Class for frequency-domain beamformers"""
    def __init__(self, host_correlator, log_level=logging.INFO, simulate = False):
        self.c = host_correlator
        
        self.config = self.c.config 

        self.config.simulate = simulate 
       
        self.log_handler = host_correlator.log_handler
        self.syslogger = logging.getLogger('fbfsys')
        self.syslogger.addHandler(self.log_handler)
        self.syslogger.setLevel(log_level)
        self.c.b = self

        self.spead_tx = []
        for beam_index in self.beam2index(all):
            self.spead_tx.append(spead.Transmitter(spead.TransportUDPtx(self.config['bf_rx_meta_ip_str_beam%i'%beam_index], self.config['bf_rx_udp_port_beam%i'%beam_index])))
        
        self.syslogger.info('Beamformer created')

#    def get_crosspol_order(self):
#        "Returns the order of the cross-pol terms out the B engines"
#        pol1=self.config['rev_pol_map'][0]
#        pol2=self.config['rev_pol_map'][1]
#        return (pol1+pol1,pol2+pol2,pol1+pol2,pol2+pol1) 

	#-----------------------
	#  helper functions
	#-----------------------

    def get_param(self, param):
    
        try:
            value = self.config[param]
        except:
            self.syslogger.error('get_param: error getting value of self.config[%s]'%param)
            raise RuntimeError('get_param: error getting value of self.config[%s]'%param)
        return value    

    def set_param(self, param, value):
        try:
            self.config[param] = value
        except:
            self.syslogger.error('get_param: error setting value of self.config[%s]'%param)
            raise RuntimeError('get_param: error setting value of self.config[%s]'%param)

    def get_beam_param(self, beams, param):

        values = []

        beams = self.beams2beams(beams)

        beam_indices = self.beam2index(beams)        
        if len(beam_indices) == 0:
            self.syslogger.error('get_beam_param: error locating beams')
            raise RuntimeError('get_beam_param: error locating beams')
        
        for beam_index in beam_indices:
            values.append(self.get_param('bf_%s_beam%d' %(param, beam_index)))

        #for single item 
        if len(values) == 1:
            values = values[0]

        return values

    def set_beam_param(self, beams, param, values):

        beams = self.beams2beams(beams)
        #passing a list of length 1 same as passing a value
        if type(values) == list and len(values) == 1:
            values = values[0]

        #check vector lengths match up
        if type(values) == list and len(values) != len(beams):
            self.syslogger.error('set_beam_param: beam vector must be same length as value vector if passing many values')
            return        
        
        beam_indices = self.beam2index(beams)        
        if len(beam_indices) == 0:
            self.syslogger.error('set_beam_param: error locating beams')
            raise RuntimeError('set_beam_param: error locating beams')

        for index, beam_index in enumerate(beam_indices):
            if type(values) == list:
                value = values[index]
            else:
                value = values
    
            self.set_param('bf_%s_beam%d' %(param, beam_index), value) 

    def get_fpgas(self):

        #if doing dummy load (no correlator), use roach names as have not got fpgas yet
        if self.config.simulate == False:
            try: 
                all_fpgas = self.c.xfpgas
            except:
                self.syslogger.error('get_fpgas: error accessing self.c.xfpgas')
                raise RuntimeError('get_fpgas: error accessing self.c.xfpgas')
        else:
            try: 
                all_fpgas = self.c.xsrvs
            except:    
                self.syslogger.error('get_fpgas: error accessing self.c.xsrvs')
                raise RuntimeError('get_fpgas: error accessing self.c.xsrvs')
       
        return all_fpgas 

    def get_bfs(self):
        """get bf blocks per fpga"""
        all_bfs = range(self.get_param('bf_be_per_fpga'))
        return all_bfs

    def get_beams(self):
        """get a list of beam names in system"""
        all_beams = []

        n_beams = self.get_param('bf_n_beams')

        for beam_index in range(n_beams):
            all_beams.append(self.get_param('bf_name_beam%i'%beam_index))
 
        return all_beams    

    def beams2beams(self,beams=all):
        """expands all, None etc into valid beam names. Checks for valid beam names"""
        new_beams = []
        
        if beams == None:
            return

        all_beams = self.get_beams()
        
        if beams == all:
            new_beams = all_beams
        else:
            if type(beams) == str:
		beams = [beams]

            #weed out beam names that do not occur
            for beam in beams:
                try:
                    all_beams.index(beam)
                    new_beams.append(beam)
                except:
                    self.syslogger.error('beams2beams: %s not found in our system'%beam)
                    raise RuntimeError('beams2beams: %s not found in our system'%beam)

        return new_beams

    def beam2index(self, beams=all):
        """returns index of beam with specified name"""
        indices = []

        #expand all etc, check for valid names etc
        beams = self.beams2beams(beams)       

	all_beams = self.get_beams()
 
        for beam in beams:
            indices.append(all_beams.index(beam))
        
        return indices 

    def frequency2fpgas(self, frequencies=all, fft_bins=[], unique=False):
        """returns fpgas associated with frequencies specified. unique only returns unique fpgas"""
        fpgas = []
       
        if len(fft_bins) == 0:
            fft_bins = self.frequency2fft_bin(frequencies)

        all_fpgas = self.get_fpgas()
        
        n_chans = self.config['n_chans']
        n_chans_per_fpga = n_chans/len(all_fpgas)

        prev_index = -1
        for fft_bin in fft_bins:
            index = numpy.int(fft_bin/n_chans_per_fpga) #floor built in
            if (unique == False) or index != prev_index:
                fpgas.append(all_fpgas[index])
            prev_index = index        

        return fpgas

    def frequency2bf_label(self, frequencies=all, fft_bins=[], unique=False): 
        """returns bf labels associated with the frequencies specified"""
 
	bf_labels = []
        bf_be_per_fpga = len(self.get_bfs()) 
	bf_indices = self.frequency2bf_index(frequencies, fft_bins, unique=unique)

	for bf_index in bf_indices:
	    bf_labels.append(numpy.mod(bf_index, bf_be_per_fpga))

	return bf_labels

    def frequency2bf_index(self, frequencies=all, fft_bins=[], unique=False):
        """returns bf indices associated with the frequencies specified"""

        bf_indices = []

        if len(fft_bins) == 0:
            fft_bins = self.frequency2fft_bin(frequencies)

        n_fpgas = len(self.get_fpgas())
        bf_be_per_fpga = len(self.get_bfs()) 
        n_bfs = n_fpgas*bf_be_per_fpga
        n_chans = self.get_param('n_chans')
        n_chans_per_bf = n_chans/n_bfs

	if max(fft_bins)>n_chans-1 or min(fft_bins) < 0:
            self.syslogger.error('frequency2bf_index: fft bin/s out of range')
            raise RuntimeError('frequency2bf_index: fft bin/s out of range')

        for fft_bin in fft_bins:
            bf_index = fft_bin/n_chans_per_bf
	    if unique == False or bf_indices.count(bf_index) == 0:
	        bf_indices.append(fft_bin/n_chans_per_bf)
        
        return bf_indices
 
    def frequency2frequency_reg_index(self, frequencies=all, fft_bins=[]):
        """Returns list of values to write into frequency register corresponding to frequency specified"""
        indices = []

        if len(fft_bins) == 0:
            fft_bins = self.frequency2fft_bin(frequencies)

        n_chans = self.get_param('n_chans')
        bf_be_per_fpga = len(self.get_bfs()) 
        n_fpgas = len(self.get_fpgas())
        divisions = n_fpgas * bf_be_per_fpga
	
        if max(fft_bins)>n_chans-1 or min(fft_bins) < 0:
            self.syslogger.error('frequency2frequency_reg_index: fft bin/s out of range')
            raise RuntimeError('frequency2frequency_reg_index: fft bin/s out of range')

        for fft_bin in fft_bins:
            indices.append(numpy.mod(fft_bin, n_chans/divisions))

        return indices

    def frequency2fft_bin(self, frequencies=all):
        """returns fft bin associated with specified frequencies""" 
        fft_bins = []
    
        n_chans = self.get_param('n_chans')
 
        if frequencies == None: 
            fft_bins = []
        elif frequencies == all:
            fft_bins = range(n_chans)
        else:
            bandwidth = (self.get_param('adc_clk')/2)
            start_freq = 0
            channel_width = bandwidth/n_chans
            for frequency in frequencies:
                frequency_normalised = numpy.mod((frequency-start_freq)+channel_width/2, bandwidth)
                fft_bins.append(numpy.int(frequency_normalised/channel_width)) #conversion to int with truncation
        
        return fft_bins
    
    def get_bf_bandwidth(self):
	"""Returns the bandwidth for one bf engine"""
        
	bandwidth = (self.get_param('adc_clk')/2)
        bf_be_per_fpga = len(self.get_bfs()) 
        n_fpgas = len(self.get_fpgas())
   
	bf_bandwidth = float(bandwidth)/(bf_be_per_fpga*n_fpgas)
	return bf_bandwidth 

    def get_bf_fft_bins(self):
	"""Returns the number of fft bins for one bf engine"""
        
	n_chans = self.config['n_chans']
        bf_be_per_fpga = len(self.get_bfs()) 
        n_fpgas = len(self.get_fpgas())

	bf_fft_bins = n_chans/(bf_be_per_fpga*n_fpgas)
	return bf_fft_bins	

    def get_fft_bin_bandwidth(self):
	"""get bandwidth of single fft bin"""
	n_chans = self.get_param('n_chans')
        bandwidth = self.get_param('adc_clk')/2

	fft_bin_bandwidth = bandwidth/n_chans
	return fft_bin_bandwidth

    def fft_bin2frequency(self, fft_bins=all):
        """returns a list of centre frequencies associated with the fft bins supplied"""
	frequencies = []
	n_chans = self.get_param('n_chans')

	if fft_bins == all:
	    fft_bins = range(n_chans)

	if type(fft_bins) == int:
	    fft_bins = [fft_bins]

	if max(fft_bins) > n_chans or min(fft_bins) < 0:
            self.syslogger.error("fft_bin2frequency: fft_bins out of range 0 -> %d"%(n_chans-1))
            raise RuntimeError("fft_bin2frequency: fft_bins out of range 0 -> %d"%(n_chans-1))
	    
        bandwidth = self.get_param('adc_clk')/2
	
	for fft_bin in fft_bins:
	    frequencies.append((float(fft_bin)/n_chans)*bandwidth)

	return frequencies

    def frequency2fpga_bf(self, frequencies=all, fft_bins=[], unique=False):
        """returns a list of dictionaries {fpga, beamformer_index} based on frequency. unique gives only unique values"""
        locations = []
    
        if unique != True and unique != False:
            self.syslogger.error("frequency2fpga_bf: unique must be True or False")
            raise RuntimeError("frequency2fpga_bf: unique must be True or False")

        if len(fft_bins) == 0:
            fft_bins = self.frequency2fft_bin(frequencies)
        
        fpgas = self.frequency2fpgas(fft_bins=fft_bins)
        bfs = self.frequency2bf_label(fft_bins=fft_bins)
       
        if len(fpgas) != len(bfs):
            self.syslogger.error("frequency2fpga_bf: fpga and bfs associated with frequencies not the same length")
            raise RuntimeError("frequency2fpga_bf: fpga and bfs associated with frequencies not the same length")
        else:
            pfpga = [] 
            pbf = []
            for index in range(len(fpgas)):
                fpga = fpgas[index]; bf = bfs[index]
                if (unique == False) or (pfpga != fpga or pbf != bf):
                    locations.append({'fpga': fpga, 'bf': bf})
                pbf = bf 
                pfpga = fpga

        return locations

    def beam_frequency2location_fpga_bf(self, beams=all, frequencies=all, fft_bins=[], unique=False):
        """returns list of dictionaries {location, fpga, beamformer index} based on beam name, and frequency"""
       
        indices = [] 

        #get beam locations 
        locations = self.beam2location(beams)

        #get fpgas and bfs
        fpgas_bfs = self.frequency2fpga_bf(frequencies, fft_bins, unique)

        for location in locations:            
            for fpga_bf in fpgas_bfs:
                fpga = fpga_bf['fpga']
                bf = fpga_bf['bf']
                indices.append({'location': location, 'fpga': fpga, 'bf': bf})

        return indices         
   
    def beam2location(self, beams=all):
        """returns location of beam with associated name or index"""

        locations = []

        beams = self.beams2beams(beams)

        for beam in beams:
            beam_location = self.get_beam_param(beam, 'location')
            locations.append(beam_location)
       
        return locations 
 
    def antenna2antenna_indices(self, antennas=all, antenna_indices=[]):

        #TODO include lookup of name to input
        n_ants = self.config['n_ants']

        if len(antenna_indices) == 0:
            if antennas==all:
                antenna_indices = range(n_ants)
            
        return antenna_indices

    def write_int(self, device_name, data, offset=0, frequencies=all, fft_bins=[]):
        """Writes data to all devices on all bfs in all fpgas associated with the frequencies specified"""
        #get all unique fpgas, bfs associated with this beam 
        targets = self.frequency2fpga_bf(frequencies, fft_bins, unique=True)
        
        if len(data) > 1 and len(targets) != len(data): 
            self.syslogger.error('write_int: many data but size (%d) does not match length of targets (%d)'%(len(data), len(targets)))
            return #TODO raise exception?

        for target_index,target in enumerate(targets):
            name = '%s%s_%s' %(self.config['bf_register_prefix'], target['bf'], device_name)
            if len(data) == 1: #write of same value to many places
                datum = data[0]
            else:
                datum = data[target_index]
 
            #pretend to write if no FPGA
            if self.config.simulate == True:
                print 'dummy write of 0x%.8x to %s:%s offset %i'%(datum, target['fpga'], name, offset)
            else:
                try:
                    target['fpga'].write_int(device_name=name, integer=datum, offset=offset)
                except:
                    self.syslogger.error('write_int: error writing of 0x%.8x to %s:%s offset %i' %(datum, target['fpga'], name, offset))
    
    def read_int(self, device_name, offset=0, frequencies=all, fft_bins=[]):
        """Reads data from all devices on all bfs in all fpgas associated with the frequencies specified"""
        #get all unique fpgas, bfs associated with the specified frequencies 
        values = []
        targets = self.frequency2fpga_bf(frequencies, fft_bins, unique=True)
        
        for target_index,target in enumerate(targets):
            name = '%s%s_%s' %(self.config['bf_register_prefix'], target['bf'], device_name)
 
            #pretend to read if no FPGA
            if self.config.simulate == True:
                print 'dummy read from %s:%s offset %i'%(target['fpga'], name, offset)
            else:
                try:
                    values.append(target['fpga'].read_int(device_name=name))
                except:
                    self.syslogger.error('read_int: error reading from %s:%s offset %i' %(target['fpga'], name, offset))

	return values
    
    def bf_control_lookup(self, destination, write='on', read='on'):
        control = 0
        if destination == 'duplicate':
            id = 0
        elif destination == 'calibrate':
            id = 1
        elif destination == 'steer':
            id = 2
        elif destination == 'combine':
            id = 3
        elif destination == 'visibility':
            id = 4
        elif destination == 'accumulate':
            id = 5
        elif destination == 'requantise':
            id = 6
        elif destination == 'filter':
            id = 7
        else:
            self.syslogger.error('bf_control_lookup: invalid destination: %s' %destination)
           
        if write == 'on':
            control = control | (0x00000001 << id)
        if read == 'on':
            control = control | (id << 16) 
        return control

    def bf_read_int(self, beam, destination, offset=0, antennas=None, frequencies=None, fft_bins=[]):
        """read from destination in the bf block for a particular beam"""
        
        values = []
        if destination == 'calibrate':
            if antennas == None:
                self.syslogger.error('bf_read_int: need to specify an antenna when reading from calibrate block')
                return
            if frequencies==None and len(fft_bins)==0:
                self.syslogger.error('bf_read_int: need to specify a frequency or fft bin when reading from calibrate block')
                return
        elif destination == 'filter':
            if antennas != None:
                self.syslogger.error('bf_read_int: can''t specify antenna when reading from filter block')
                return
        else:
            self.syslogger.error('bf_read_int: invalid destination: %s' %destination)
            return
         
        if len(fft_bins) == 0:
            fft_bins = self.frequency2fft_bin(frequencies)

        location = self.beam2location(beams=beam)
        
        if len(location) == 0:
            print 'bf_read_int: you must specify a valid beam to write to'
            return

        #look up control value required to read 
        control = self.bf_control_lookup(destination, write='off', read='on')
        print 'bf_read_int: disabling writes, setting up reads' 
        self.write_int('control', [control], 0, fft_bins=fft_bins)
        
        antenna_indices = self.antenna2antenna_indices(antennas=antennas)

        print 'bf_read_int: setting up location' 
        #set up target stream (location of beam in set )
        self.write_int('stream', [location[0]], 0, fft_bins=fft_bins)

        #go through antennas (normally just one but may be all or none)
        for antenna_index in antenna_indices:
            
            print 'bf_read_int: setting up antenna' 
            #set up antenna register
            self.write_int('antenna', [antenna_index], 0, fft_bins=fft_bins)
           
            #cycle through frequencies (cannot have frequencies without antenna component) 
            for index, fft_bin in enumerate(fft_bins):
                
                frequency = frequencies[index]

                print 'bf_read_int: setting up frequency' 
                #set up frequency register
                self.write_int('frequency', [self.frequency2frequency_reg_indices(fft_bins=[fft_bin])], 0, fft_bins=[fft_bin])
              
            #if no frequency component, read 
            if len(fft_bins) == 0:
                #read
                print 'bf_read_int: reading for no frequencies' 
                values = self.read_int('value_out', offset=0, fft_bins=fft_bins)      

        if len(antenna_indices) == 0:
            #read
            print 'bf_read_int: reading for no antennas' 
            values = self.read_int('value_out', offset=0, fft_bins=fft_bins)     
	
	return values 

    #TODO ensure this function call is monotonic due to potential race conditions
    def bf_write_int(self, destination, data, offset=0, beams=all, antennas=None, frequencies=None, fft_bins=[]):
        """write to various destinations in the bf block for a particular beam"""

        if destination == 'calibrate':
            if antennas == None:
                self.syslogger.error('bf_write_int: need to specify an antenna when writing to calibrate block')
                return
            if frequencies == None and len(fft_bins) == 0:
                self.syslogger.error('bf_write_int: need to specify a frequency or fft bin when writing to calibrate block')
                return
        elif destination == 'filter':
            if antennas != None:
                self.syslogger.error('bf_write_int: can''t specify antenna for filter block')
                return
        else:
            self.syslogger.error('bf_write_int: invalid destination: %s' %destination)
            return

        if len(fft_bins) == 0:
            fft_bins = self.frequency2fft_bin(frequencies)

        locations = self.beam2location(beams=beams)
        
        if len(locations) == 0:
            print 'bf_write_int: you must specify a valid beam to write to'
            return

        #disable writes
        print 'bf_write_int: disabling everything' 
        self.write_int('control', [0x0], 0, fft_bins=fft_bins)
        
        if len(data) == 1:

            print 'bf_write_int: setting up data for single data item' 
            #set up the value to be written
            self.write_int('value_in', data, offset, fft_bins=fft_bins)

        #look up control value required to write when triggering write
        control = self.bf_control_lookup(destination, write='on', read='on')
        
        antenna_indices = self.antenna2antenna_indices(antennas=antennas)

        #cycle through beams to be written to
        for location in locations:
           
            print 'bf_write_int: setting up location' 
            #set up target stream (location of beam in set )
            self.write_int('stream', [location], 0, fft_bins=fft_bins)

            #go through antennas (normally just one but may be all or none)
            for antenna_index in antenna_indices:
                
                print 'bf_write_int: setting up antenna' 
                #set up antenna register
                self.write_int('antenna', [antenna_index], 0, fft_bins=fft_bins)
               
                #cycle through frequencies (cannot have frequencies without antenna component) 
                for index, fft_bin in enumerate(fft_bins):
                    
                    frequency = frequencies[index]

                    print 'bf_write_int: setting up frequency' 
                    #set up frequency register
                    self.write_int('frequency', [self.frequency2frequency_reg_indices(fft_bins=[fft_bin])], 0, fft_bins=[fft_bin])
                  
                    #we have a vector of data (one for every frequency)
                    if len(data) > 1:
                        #set up the value to be written
                        self.write_int('value_in', [data[index]], 0, fft_bins=fft_bins)
 
                    #trigger the write
                    print 'bf_write_int: triggering for vector of frequencies' 
                    self.write_int('control', [control], 0, fft_bins=fft_bins)      

                #if no frequency component, trigger
                if len(fft_bins) == 0:
                    #trigger the write
                    print 'bf_write_int: triggering for no frequencies' 
                    self.write_int('control', [control], 0, fft_bins=fft_bins)      
            
            #if no antenna component, trigger write
            if len(antenna_indices) == 0:
                #trigger the write
                print 'bf_write_int: triggering for no antennas' 
                self.write_int('control', [control], 0, fft_bins=fft_bins)      

    def cf_bw2fft_bins(self, centre_frequency, bandwidth):
        """returns fft bins associated with provided centre_frequency and bandwidth"""
        bins = []    
    
        adc_clk = self.config['adc_clk']
        n_chans = self.config['n_chans']
        
        #TODO spectral line mode systems??
        if (centre_frequency-bandwidth/2) < 0 or (centre_frequency+bandwidth/2) > adc_clk/2:
            self.sys_logger.error('cf_bw2fft_bins: band specified out of range of our system')
            print 'band specified out of range'
            return
       
        #full band required
        if bandwidth == adc_clk/2:
            bins = range(n_chans) 
        else:    
            #get fft bin for edge frequencies
            edge_bins = self.frequency2fft_bin(frequencies=[centre_frequency-bandwidth/2, centre_frequency+bandwidth/2])
            bins = range(edge_bins[0], edge_bins[1]+1)

        return bins

    def get_enabled_fft_bins(self, beam):
        """Returns fft bins representing band that is enabled for beam"""
        bins = []        

        cf = self.get_beam_param(beam, 'centre_frequency')  
        bw = self.get_beam_param(beam, 'bandwidth')  
    
        bins = self.cf_bw2fft_bins(cf, bw)
        return bins

    def get_disabled_fft_bins(self,beam):
        """Returns fft bins representing band that is disabled for beam"""
        
        all_bins = self.frequency2fft_bin(frequencies=all)
        enabled_bins = self.get_enabled_fft_bins(beam)
        for fft_bin in enabled_bins:
            all_bins.remove(fft_bin)
        return all_bins	
        
#-----------------------------------
#  Interface for standard operation
#-----------------------------------

    def initialise(self, set_cal = True, config_output = True, send_spead = True):
        """Initialises the system and checks for errors."""
        
	#disable all beams
        print 'initialise: stopping transmission from all beams'
        self.tx_stop(all, spead_stop=False)
	
	#TODO need small sleep here as heaps flush
	       
#        if self.config.simulate == False: 
#            if self.tx_status_get(): self.tx_stop()
#        else:
        #print 'initialise: simulating stopping transmission'

        self.spead_config_basics()
#        self.spead_config_output()
        self.config_udp_output()

#        if set_cal: self.cal_set_all()
#        else: self.syslogger.info('Skipped calibration config of beamformer.')

#        if send_spead:
#            self.spead_issue_all()

        self.syslogger.info("Beamformer initialisation complete.")
    
    def tx_start(self, beams=all):
        """Start outputting SPEAD products. Only works for systems with 10GbE output atm.""" 
        if self.config['out_type'] == '10gbe':

            #NOTE that the order of the following operations is significant
            #output from bfs will be enabled if any component frequencies are required

            #convert to actual beam names
            beams = self.beams2beams(beams)
            beam_indices = self.beam2index(beams)

            for index,beam in enumerate(beams):

                beam_index = beam_indices[index]

                #get frequency_indices associated with disabled parts of beam
                disabled_fft_bins = self.get_disabled_fft_bins(beam)
               
                if len(disabled_fft_bins) > 0: 
                    if self.config.simulate == True:
                        print 'disabling excluded bfs'

                    #disable bfs not required via the filter block in the beamformer
                    self.bf_write_int(destination='filter', data=[0x0], offset=0x0, beams=beam, fft_bins=disabled_fft_bins)  
                    
                    if self.config.simulate == True:
                        print 'configuring excluded bfs'

                    #configure disabled beamformers to output HEAP size of 0
                    bf_config = ((beam_index << 16) & 0xffff0000 | (0 << 8) & 0x0000ff00 | 0 & 0x000000ff) 
                    self.write_int('cfg%i'%beam_index, [bf_config], 0, fft_bins=disabled_fft_bins)
                
                #get frequency_indices associated with enabled parts of beams
                enabled_fft_bins = self.get_enabled_fft_bins(beam)
        
                #generate vector of values that will match the number of bfs in the list
                fpga_bf_e = self.frequency2fpga_bf(fft_bins=enabled_fft_bins, unique=True)
                bf_config = []
                for offset in range(len(fpga_bf_e)):
                    bf_config.append((beam_index << 16) & 0xffff0000 | (len(fpga_bf_e) << 8) & 0x0000ff00 | offset & 0x000000ff)
                
                if self.config.simulate == True:
                    print 'configuring included bfs'
                self.write_int('cfg%i'%beam_index, bf_config, 0, fft_bins=enabled_fft_bins)

                if self.config.simulate == True:
                    print 'enabling included bfs'
                #lastly enable those parts
                self.bf_write_int(destination='filter', data=[0x1], offset=0x0, beams=beam, fft_bins = enabled_fft_bins)  
                self.syslogger.info('Output for %s started' %(beam))
        else:
            self.syslogger.error('Sorry, your output type is not supported. Could not enable output.')
    
    def tx_stop(self, beams=all, spead_stop=True):
        """Stops outputting SPEAD data over 10GbE links for specified beams. Sends SPEAD packets indicating end of stream if required"""

        if self.config['out_type'] == '10gbe':
            #convert to actual beam names
            beams = self.beams2beams(beams)
            beam_indices = self.beam2index(beams)

            for index,beam in enumerate(beams):

                beam_index = beam_indices[index]

                #disable all bf outputs
                self.bf_write_int(destination='filter', data=[0x0], offset=0x0, beams=beams)  

                self.syslogger.info("Beamformer output paused for beam %s" %beam)
                if spead_stop:
                    if self.config.simulate == True:
                        print 'tx_stop: dummy ending SPEAD stream for beam %s' %beam
                    else:
                        tx_temp = spead.Transmitter(spead.TransportUDPtx(self.config['bf_rx_meta_ip_str_beam%d'%beam_index], self.config['bf_rx_udp_port_beam%d'%beam_index]))
                        tx_temp.end()
                    self.syslogger.info("Sent SPEAD end-of-stream notification for beam %s" %beam)
                else:
                    self.syslogger.info("Did not send SPEAD end-of-stream notification for beam %s" %beam)
        else:
            self.syslogger.warn("Sorry, your output type is not supported. Cannot disable output for beam %s." %(beam))
    
    #untested
    #TODO
    def tx_status_get(self, beam):
        """Returns boolean true/false if the beamformer is currently outputting data. Currently only works on systems with 10GbE output."""
        
	if self.get_param('out_type')!='10gbe': 
            self.syslogger.warn("This function only works for systems with 10GbE output!")
            return False
        
	rv=True

        #check 10Ge cores are not in reset
        stat=self.c.xeng_ctrl_get_all()
        for xn in stat:
            if xn['gbe_out_rst']!=False: rv=False
        
        self.syslogger.info('10Ge output is currently %s'%('enabled' if rv else 'disabled'))

        #read output status of beams
	mask = self.bf_read_int(beam=beam, destination='filter')
	
	#look to see if any portion in enabled
 	if mask.count(1) != 0: rv = rv
	else: rv = False

        return rv

    def config_udp_output(self, beams=all, dest_ip_str=None, dest_port=None):
        """Configures the destination IP and port for B engine outputs. dest_port and dest_ip are optional parameters to override the config file defaults."""
        beams = self.beams2beams(beams)

        for beam in beams:

            if dest_ip_str==None:
                dest_ip_str=self.get_beam_param(beam, 'rx_udp_ip_str')
            else:
                self.set_beam_param(beam, 'rx_udp_ip_str', dest_ip_str)
                self.set_beam_param(beam, 'rx_udp_ip', struct.unpack('>L',socket.inet_aton(dest_ip_str))[0])
                self.set_beam_param(beam, 'rx_meta_ip_str', dest_ip_str)
                self.set_beam_param(beam, 'rx_meta_ip', struct.unpack('>L',socket.inet_aton(dest_ip_str))[0])

            if dest_port==None:
                dest_port=self.get_beam_param(beam, 'rx_udp_port')
            else:
                self.set_beam_param(beam, 'rx_udp_port', dest_port)

            beam_offset = self.get_beam_param(beam, 'location')

            dest_ip = struct.unpack('>L',socket.inet_aton(dest_ip_str))[0]

            self.write_int('dest', data=[dest_ip], offset=(beam_offset*2))                     
            self.write_int('dest', data=[dest_port], offset=(beam_offset*2+1))                     
            #each beam output from each beamformer group can be configured differently
            self.syslogger.info("Beam %s configured to output to %s:%i." %(beam, dest_ip_str, dest_port))

    def set_passband(self, beams=all, centre_frequency=None, bandwidth=None):
        """sets the centre frequency and/or bandwidth for the specified beams"""
        
        beams = self.beams2beams(beams)
        
	max_bandwidth = self.get_param('adc_clk')/2

        for beam in beams:

	    #parameter checking
	    if centre_frequency == None:
	        cf = get_beam_param(beam, 'centre_frequency')
	    else:
		cf = centre_frequency

	    if bandwidth == None:
		b = get_beam_param(beam, 'bandwidth')
	    else:
		b = bandwidth

	    if ((cf-b/2) < 0) or ((cf+b/2) > max_bandwidth):
            	self.syslogger.error('set_passband: Passband settings specified for beam %s out of range 0->%iMHz'%(beam, max_bandwidth/1000000))
	    
            if centre_frequency != None:
                self.set_beam_param(beam, 'centre_frequency', centre_frequency)

            if bandwidth != None:
                self.set_beam_param(beam, 'bandwidth', bandwidth)
        
            if centre_frequency != None or bandwidth != None:
                #restart if currently transmitting
		if self.tx_status_get(beam) == True:
		    self.tx_stop(beam)
		    self.tx_start(beam)
		    self.syslogger.info('Restarted beam %s with new passband parameters'%beam)
            
            if centre_frequency != None:
                self.syslogger.info('Centre frequency for beam %s set to %i Hz'%(beam, centre_frequency))
            if bandwidth != None:
                self.syslogger.info('Bandwidth for beam %s set to %i Hz'%(beam, bandwidth))
    
    def get_passband(self, beam):
        """gets the centre frequency and bandwidth for the specified beam"""
    
        fft_bins = self.get_enabled_fft_bins(beam)
        bfs = self.frequency2bf_index(frequency_indices=fft_bins, unique=True)
	bf_bandwidth = self.get_bf_bandwidth()
	fft_bin_bandwidth = self.get_fft_bin_bandwidth()

	#calculate start frequency accounting for frequency specified in centre of bin
	start_frequency = min(bfs)*bf_bandwidth-fft_bin_bandwidth/2
	centre_frequency = start_frequency+bf_bandwidth*(float(len(bfs))/2)

	beam_bandwidth = len(bfs) * bf_bandwidth
	
        return centre_frequency, beam_bandwidth

#   CALIBRATION 

    #TODO
    def cal_set_all(self, beam, init_poly = [], init_coeffs = []):
        """Initialise all antennas for all beams' calibration factors to given polynomial. If no polynomial or coefficients are given, use defaults from config file."""

        for in_n, ant_str in enumerate(self.config._get_ant_mapping_list()):
            self.cal_spectrum_set(beam = beam, ant_str = ant_str, init_coeffs = init_coeffs, init_poly = init_poly)
        self.syslogger.info('Set all calibration values for beam %s.'%beam)
    
    #untested
    def cal_default_get(self, beam, ant_str):
        "Fetches the default calibration configuration from the config file and returns a list of the coefficients for a given beam and antenna." 

        n_coeffs = self.get_param('n_chans')
        input_n  = self.c.map_ant_to_input(ant_str)

        bf_cal_default = self.get_param('bf_cal_default')
        if bf_cal_default == 'coeffs':
            calibration = self.get_beam_param(beam, 'cal_coeffs_input%i'%input_n)

        elif bf_cal_default == 'poly':
            poly = self.get_beam_param(beam, 'cal_poly_input%i' %input_n)
            calibration = numpy.polyval(poly, range(n_coeffs))
            if self.get_param('bf_cal_type') == 'complex':
                calibration = [cal+0*1j for cal in calibration]
        else: 
            raise RuntimeError("cal_default_get: Your default beamformer calibration type, %s, is not understood." %bf_cal_default)
                
        if len(calibration) != n_coeffs:
            raise RuntimeError("cal_default_get: Something's wrong. I have %i calibration coefficients when I should have %i." % (len(calibration), n_coeffs))
        return calibration

    def cal_spectrum_get(self, beams, beam_indices, input_n):
        """Retrieves the calibration settings currently programmed in all bengines for the given beam and antenna. Returns an array of length n_chans."""

    #untested
    def cal_data_set(self, beam, ant_str, frequencies, data):
        """Set a given beam and antenna calibration setting to given value"""

        for index, datum in enumerate(data):

            datum_real = numpy.real(datum)
            datum_imag = numpy.imag(datum)        

            if max(datum_real) > ((2**15)-1) or min(datum_real)<-((2**15)-1):
                self.syslogger.error('cal_data_set:beamformer real calibration values out of range')
            if max(datum_imag) > ((2**15)-1) or min(datum_imag)<-((2**15)-1):
                self.syslogger.error('beamformer imaginary calibration values out of range')
            #pack real and imaginary values
            values[index] = (numpy.uint32(datum_real) << 16) | (numpy.uint32(datum_imag) | 0x0000FFFF)
     
        bf_write_int('calibrate', values, 0, beams=beams, beam_indices=beam_indices, antennas=ants, frequencies=frequencies)
    
    #untested
    def cal_spectrum_set(self, beam, ants, init_coeffs = [], init_poly = []):
        """Set given beam and antenna calibration settings to given co-efficients."""

        n_coeffs = self.config['n_chans'] 
        beam  = self.beam2index(beam)
        
        if init_coeffs == [] and init_poly == []: 
            coeffs = self.bf_cal_default_get(beam=beam, beam_indices=beam_indices, antenna=ants)
        elif len(init_coeffs) == n_coeffs:
            coeffs = init_coeffs
        elif len(init_coeffs)>0: 
            raise RuntimeError ('You specified %i coefficients, but there are %i cal coefficients in this design.'%(len(init_coeffs),n_coeffs))
        else:
            coeffs = numpy.polyval(init_poly, range(self.config['n_chans']))
        
        bf_cal_type = self.get_param('bf_cal_type')
        if bf_cal_type == 'scalar':
            coeffs = numpy.real(coeffs) 
        elif self.config('bf_cal_type') == 'complex':
            coeffs = numpy.array(coeffs, dtype = numpy.complex128)
        else:
            log_runtimeerror(self.floggers[ffpga_n], "Sorry, your beamformer calibration type is not supported. Expecting scalar or complex.")

        #self.floggers[ffpga_n].info('Writing new EQ coefficient values to config file...')
        #self.config.write('equalisation','eq_coeffs_%i%c'%(ant,pol),str(coeffs.tolist()))
        
#        for term, coeff in enumerate(coeffs):
#            self.floggers[ffpga_n].debug('''Initialising beamformer calibration for beam %i antenna %s, to %s.''' % (beam_n, ant_str, ffpga_n], register_name, term, str(coeff)))

        # if this is a narrowband implementation, swap the EQ values, because the Xilinx FFT output is in swapped halves
#        if self.is_narrowband():
#            coeff_str = ''.join([coeff_str[len(coeff_str)/2:], coeff_str[0:len(coeff_str)/2]])
        n_chans = self.get_param('n_chans')
        bandwidth = self.get_param('adc_clk')/2
        freqs = range(0, bandwidth, bandwidth/n_chans)

        cal_data_set(beam_name_str, ant_str, freqs, coeffs)

	#-----------
	#   SPEAD
	#-----------

    def spead_config_basics(self):
        '''Sets up spead item and data values'''
        
        #set up data and timestamp ids
        if self.config.simulate == True:
            print 'spead_config_basics: dummy write to beng_data_id on all x engines'
            print 'spead_config_basics: dummy write to beng_time_id on all x engines'
        else:
                #TODO data id should increment for beams
            self.c.xwrite_int_all('beng_data_id', (0x000000 | 0xB000)) #data id
            self.c.xwrite_int_all('beng_time_id', (0x800000 | 5632) ) #same timestamp id as for correlator
    
    def spead_config_output(self, beams=all):
        '''Sets up configuration registers controlling SPEAD output for beams specified'''
        
        beams = self.beams2beams(beams)
        beam_indices = self.beam2index(beams) 
        bf_prefix = self.get_param('bf_register_prefix')
        n_ants = self.get_param('n_ants')
        bf_be_per_fpga = self.get_param('bf_be_per_fpga')        

        #go through all beams
        for index, beam in enumerate(beams):
            location = self.get_beam_param(beam, 'location')        
            beam_id = beam_indices[index]

            #TODO cater for not whole range 
            bf_indices = range(n_ants * bf_be_per_fpga)
 
            beam_fpgas = self.get_fpgas()

            for index in range(len(bf_indices)):
                bf_index = bf_indices[index]
                fpga = beam_fpgas[int(bf_index/bf_be_per_fpga)] #truncate
                bf = bf_index%bf_be_per_fpga
                bf_config_reg = '%s%i_cfg%i'%(bf_prefix, bf, location)
                offset = index #offset in heap depends on frequency band which increases linearly through fpga and bf
                
                bf_config = (beam_id << 16) & 0xffff0000 | (len(bf_indices) << 8) & 0x0000ff00 | offset & 0x000000ff  
                if self.simulate == False:
                    fpga.write_int(bf_config_reg, bf_config, 0)

    def spead_labelling_issue(self, beams=all):
        """Issues the SPEAD metadata packets describing the labelling/location/connections of the system's analogue inputs."""

        spead_ig=spead.ItemGroup()

        spead_ig.add_item(name="input_labelling",id=0x100E,
            description="The physical location of each antenna connection.",
            init_val=numpy.array([(ant_str,input_n,lru,feng_input) for (ant_str,input_n,lru,feng_input) in self.adc_lru_mapping_get()]))
        
        beam_indices = self.beam2index(beams)
        
        for idx in beam_indices:
            ig = spead_ig
            self.spead_tx[idx].send_heap(ig.get_heap())
        
            self.syslogger.info("Issued SPEAD metadata describing baseline labelling and input mapping for beam %s to %s:%i." %(self.config['bf_name_beam%i'%idx], self.config['bf_rx_meta_ip_str_beam%i'%idx], self.config['bf_rx_udp_port_beam%i'%idx]))

    def spead_static_meta_issue(self, beams=all):
        """ Issues the SPEAD metadata packets containing the payload and options descriptors and unpack sequences."""

#        spead stuff that does not care about beam
        spead_ig=spead.ItemGroup()

        spead_ig.add_item(name="adc_clk",id=0x1007,
            description="Clock rate of ADC (samples per second).",
            shape=[],fmt=spead.mkfmt(('u',64)),
            init_val=self.config['adc_clk'])

        #TODO
#        spead_ig.add_item(name="n_beams",id=0x,
#            description="The total number of baselines in the data product.",
#            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
#            init_val=self.config['n_bls'])
#
        spead_ig.add_item(name="n_chans",id=0x1009,
            description="The total number of frequency channels present in any integration.",
            shape=[], fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['n_chans'])

        spead_ig.add_item(name="n_ants",id=0x100A,
            description="The total number of dual-pol antennas in the system.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['n_ants'])

        #TODO
#       spead_ig.add_item(name="n_bengs",id=0x,
#            description="The total number of B engines for this beam-group.",
#            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
#            init_val=self.config['n_xeng'])
        
        #1015/1016 are taken (see time_metadata_issue below)

        spead_ig.add_item(name="requant_bits",id=0x1020,
            description="Number of bits after requantisation in the F engines (post FFT and any phasing stages).",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['feng_bits'])

        spead_ig.add_item(name="feng_pkt_len",id=0x1021,
            description="Payload size of 10GbE packet exchange between F and X engines in 64 bit words. Usually equal to the number of spectra accumulated inside X engine. F-engine correlator internals.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['10gbe_pkt_len'])

#TODO ADD VERSION INFO!

        #TODO
#        spead_ig.add_item(name="b_per_fpga",id=0x,
#            description="Number of B engines per FPGA.",
#            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
#            init_val=self.config['x_per_fpga'])

        #TODO
        spead_ig.add_item(name="ddc_mix_freq",id=0x1043,
            description="Digital downconverter mixing freqency as a fraction of the ADC sampling frequency. eg: 0.25. Set to zero if no DDC is present.",
            shape=[],fmt=spead.mkfmt(('f',64)),
            init_val=self.config['ddc_mix_freq'])

#       spead_ig.add_item(name="ddc_bandwidth",id=0x1044,
#            description="Digitally processed bandwidth, post DDC, in Hz.",
#            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
#            init_val=self.confsig['bandwidth']) #/self.config['ddc_decimation']) config's bandwidth is already divided by ddc decimation

#0x1044 should be ddc_bandwidth, not ddc_decimation.
#       spead_ig.add_item(name="ddc_decimation",id=0x1044,
#            description="Frequency decimation of the digital downconverter (determines how much bandwidth is processed) eg: 4",
#            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
#            init_val=self.config['ddc_decimation'])

        spead_ig.add_item(name="adc_bits",id=0x1045,
            description="ADC quantisation (bits).",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['adc_bits'])

        beam_indices = self.beam2index(beams)
        for idx in beam_indices:
            ig = spead_ig      
 
            #TODO get these properly
            ig.add_item(name="center_freq",id=0x1011,
                description="The center frequency of the DBE in Hz, 64-bit IEEE floating-point number.",
                shape=[],fmt=spead.mkfmt(('f',64)),
                init_val=self.config['center_freq'])

            ig.add_item(name="bandwidth",id=0x1013,
                description="The analogue bandwidth of the digitally processed signal in Hz.",
                shape=[],fmt=spead.mkfmt(('f',64)),
                init_val=self.config['bandwidth'])
        
            self.spead_tx[idx].send_heap(ig.get_heap())
            self.syslogger.info("Issued misc SPEAD metadata for beam %s to %s:%i." %(self.config['bf_name_beam%d'], self.config['bf_rx_meta_ip_str_beam'%idx], self.config['rx_udp_port_beam%i'%idx]))

    def spead_time_meta_issue(self, beams=all):
        """Issues a SPEAD packet to notify the receiver that we've resync'd the system, acc len has changed etc."""
        
        spead_ig = spead.ItemGroup()

        #sync time
        spead_ig.add_item(name='sync_time',id=0x1027,
            description="Time at which the system was last synchronised (armed and triggered by a 1PPS) in seconds since the Unix Epoch.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['sync_time'])

        #scale factor for timestamp
        spead_ig.add_item(name="scale_factor_timestamp",id=0x1046,
            description="Timestamp scaling factor. Divide the SPEAD data packet timestamp by this number to get back to seconds since last sync.",
            shape=[],fmt=spead.mkfmt(('f',64)),
            init_val=self.config['spead_timestamp_scale_factor'])
            
        beam_indices = self.beam2index(beams)
        for idx in beam_indices:
                ig = spead_ig

                self.spead_tx[idx].send_heap(ig.get_heap())
                self.syslogger.info("Issued SPEAD timing metadata for beam %s to %s:%i." %(self.config['bf_name_beam%d'], self.config['bf_rx_meta_ip_str_beam'%idx], self.config['rx_udp_port_beam%i'%idx]))

    #TODO
#    def spead_cal_meta_issue(self):
#        """Issues a SPEAD heap for the calibration settings."""

    def spead_eq_meta_issue(self):
        """Issues a SPEAD heap for the RF gain and EQ settings."""
        
        beam_indices = self.beam2index(beams)
        for idx in beam_indices:
            spead_ig = spead.ItemGroup()
        
            #RF
            if self.config['adc_type'] == 'katadc':
                for input_n,ant_str in enumerate(self.config._get_ant_mapping_list()):
                    spead_ig.add_item(name="rf_gain_%i"%(input_n),id=0x1200+input_n,
                        description="The analogue RF gain applied at the ADC for input %i (ant %s) in dB."%(input_n,ant_str),
                        shape=[],fmt=spead.mkfmt(('f',64)),
                        init_val=self.config['rf_gain_%i'%(input_n)])

            #equaliser settings
            for in_n,ant_str in enumerate(self.config._get_ant_mapping_list()):
                spead_ig.add_item(name="eq_coef_%s"%(ant_str),id=0x1400+in_n,
                    description="The unitless per-channel digital scaling factors implemented prior to requantisation, post-FFT, for input %s. Complex number real,imag 32 bit integers."%(ant_str),
                    shape=[self.config['n_chans'],2],fmt=spead.mkfmt(('u',32)),
                    init_val=[[numpy.real(coeff),numpy.imag(coeff)] for coeff in self.eq_spectrum_get(ant_str)])

            self.spead_tx.send_heap(spead_ig.get_heap())
            self.syslogger.info("Issued SPEAD EG metadata for beam %s to %s:%i." %(self.config['bf_name_beam%d'], self.config['bf_rx_meta_ip_str_beam'%idx], self.config['rx_udp_port_beam%i'%idx]))

    #untested
    def spead_data_descriptor_issue(self, beams=all):
        """ Issues the SPEAD data descriptors for the HW 10GbE output, to enable receivers to decode the data."""
        #tested ok corr-0.5.0 2010-08-07
        spead_ig = spead.ItemGroup()

        #timestamp
        spead_ig.add_item(name=('timestamp'), id=0x1016,
            description='Timestamp of start of this block of data. uint counting multiples of ADC samples since last sync (sync_time, id=0x1027). Divide this number by timestamp_scale (id=0x1046) to get back to seconds since last sync when this integration was actually started. Note that the receiver will need to figure out the centre timestamp of the accumulation (eg, by adding half of int_time, id 0x1016).',
            shape=[], fmt=spead.mkfmt(('u',spead.ADDRSIZE)),init_val=0)

        beam_indices = self.beam2index(beams)
        for idx in beam_indices:
            ig = spead_ig
 
            #data item
            ig.add_item(name=(self.config['bf_name_beam%i'%idx]), id=0xB000,
                description="Raw data for bengines in the system.  Frequencies are assembled from lowest frequency to highest frequency. Frequencies come in blocks of values in time order where the number of samples in a block is given by xeng_acc_len (id 0x101F). Each value is a complex number -- two (real and imaginary) signed integers.",
                ndarray=(numpy.dtype(numpy.int8),(2,self.config['n_bls'],2)))
                
            self.spead_tx.send_heap(ig.get_heap())
            self.syslogger.info("Issued SPEAD data descriptor for beam %s to %s:%i." %(self.config['bf_name_beam%d'], self.config['bf_rx_meta_ip_str_beam'%idx], self.config['rx_udp_port_beam%i'%idx]))
    
    def spead_issue_all(self, beams=all):
        """Issues all SPEAD metadata."""

        self.spead_data_descriptor_issue(beams)
        self.spead_static_meta_issue(beams)
        self.spead_time_meta_issue(beams)
        self.spead_eq_meta_issue(beams)
        self.spead_labelling_issue(beams)

