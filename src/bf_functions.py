# /usr/bin/env python
""" 
Selection of commonly-used beamformer control functions.

Author: Jason Manley, Andrew Martens
"""
"""
Revisions:
2012-10-02 JRM Initial
2013-02-10 AM basic boresight 
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

        print 'beamformer created'

#    def get_crosspol_order(self):
#        "Returns the order of the cross-pol terms out the B engines"
#        pol1=self.config['rev_pol_map'][0]
#        pol2=self.config['rev_pol_map'][1]
#        return (pol1+pol1,pol2+pol2,pol1+pol2,pol2+pol1) 

	#-----------------------
	#  helper functions
	#-----------------------

    def get_fpgas(self):
        all_fpgas = self.c.xsrvs
        try:
            #if doing dummy load (no correlator), use roach names as have not got fpgas yet
            if self.config.simulate == False:
                all_fpgas = self.c.xfpgas
        except:
            pass
       
        return all_fpgas 

    def get_bfs(self):
        all_bfs = range(self.config['bf_be_per_fpga'])
        return all_bfs

    def frequency2fpga_index(self, frequencies=all, frequency_indices=[]):
        """returns index associated with frequency specified"""
        fpgas = []
       
        if len(frequency_indices) == 0:
            frequency_indices = self.frequency2fft_bin(frequencies)

        all_fpgas = self.get_fpgas()
        
        n_chans = self.config['n_chans']
        n_chans_per_fpga = n_chans/len(all_fpgas)

        for freq_index in frequency_indices:
            fpgas.append(all_fpgas[numpy.int(freq_index/n_chans_per_fpga)]) #floor built in
        
        return fpgas
 
    def frequency2bf_index(self, frequencies=all, frequency_indices=[]):
        """returns bf indices associated with the frequencies specified"""

        bfs = []

        if len(frequency_indices) == 0:
            frequency_indices = self.frequency2fft_bin(frequencies)

        bf_be_per_fpga = len(self.get_bfs()) 
        n_fpgas = len(self.c.xsrvs)
        n_bfs = n_fpgas*bf_be_per_fpga
        n_chans = self.config['n_chans']
        n_chans_per_bf = n_chans/n_bfs

        for freq_index in frequency_indices:
            bfs.append(numpy.int(numpy.mod(freq_index/n_chans_per_bf, bf_be_per_fpga)))
        
        return bfs 
 
    def frequency2frequency_indices(self, frequencies=all, frequency_indices=[]):
        """Returns list of values to write into frequency register associated with frequency specified"""
        indices = []

        if len(frequency_indices) == 0:
            frequency_indices = self.frequency2fft_bin(frequencies)

        n_chans = self.config['n_chans']
        bf_be_per_fpga = len(self.get_bfs()) 
        n_fpgas = len(self.c.xsrvs)
        divisions = n_fpgas * bf_be_per_fpga

        for freq in frequency_indices:
            indices.append(numpy.mod(freq, n_chans/divisions))

        return indices
    
    def frequency2fft_bin(self, frequencies=all):
        """returns fft bin associated with specified frequencies""" 
        fft_bins = []
    
        n_chans = self.config['n_chans']
 
        if frequencies == None: 
            fft_bins = []
        elif frequencies == all:
            fft_bins = range(n_chans)
        else:
            n_chans = self.config['n_chans']
            bandwidth = (self.config['adc_clk']/2)
            start_freq = 0
            channel_width = bandwidth/n_chans
            for frequency in frequencies:
                frequency_normalised = numpy.mod((frequency-start_freq)+channel_width/2, bandwidth)
                fft_bins.append(numpy.int(frequency_normalised/channel_width)) #conversion to int with truncation
        
        return fft_bins
    
    def frequency2fpga_bf(self, frequencies=all, frequency_indices=[]):
        """returns a list of dictionaries {fpga, beamformer_index} based on frequency"""
        locations = []

        if frequencies==all:
            fpgas = self.get_fpgas()
            bfs = self.get_bfs()
            for fpga in fpgas:
                for bf in bfs:
                    locations.append({'fpga': fpga, 'bf': bf})
        else:
            fpgas = frequency2fpgas(frequencies, frequency_indices)
            bfs = frequency2bfs(frequencies, frequency_indices)
            
            prev_fpga = []
            prev_bf = []
            if len(fpgas) != len(bfs):
                #TODO
                print 'fpgas and bfs lengths don''t match'
            else:
                for index in range(len(fpgas)):
                    fpga = fpgas[index]
                    bf = bfs[index]
                    if (prev_fpga != fpga) or (prev_bf != bf):
                        locations.append({'fpga': fpga, 'bf': bf}) 

        return locations

    def beam_frequency2location_fpga_bf(self, beams=all, frequencies=all, beam_indices=[], frequency_indices=[]):
        """returns list of dictionaries {location, fpga, beamformer index} based on beam name, and frequency"""
       
        indices = [] 

        #get beam locations 
        locations = self.beam2location(beams, beam_indices)

        #get fpgas 
        fpgas_bfs = self.frequency2fpga_bf(frequencies, frequency_indices)

        for location in locations:            
            for fpga_bf in fpgas_bfs:
                fpga = fpga_bf['fpga']
                bf = fpga_bf['bf']
                indices.append({'location': location, 'fpga': fpga, 'bf': bf})

        return indices         

    def beam2index(self, beams=all):
        """returns index of beam with specified name"""
        
        indices = []
        n_beams = self.config['bf_n_beams']

        if beams == None:   
            indices = []
        if beams == all:
            indices = range(n_beams) 
        else:
            for beam in beams:
                for beam_index in range(n_beams):
                    beam_name = self.config['bf_name_beam%i'%(beam_index)]

                    if (beam == beam_name):
                        indices.append(beam_index)
        
        return indices 
   
    def beam2location(self, beams=all, beam_indices=[]):
        """returns location of beam with associated name or index"""

        locations = []

        if len(beam_indices) == 0:
            beam_indices = self.beam2index(beams)

        for beam_index in beam_indices:
            beam_location = self.config['bf_location_beam%i'%(beam_index)]
            locations.append(beam_location)
        
        return locations 
 
    def antenna2antenna_indices(self, antennas=all, antenna_indices=[]):

        #TODO include lookup of name to input
        n_ants = self.config['n_ants']

        if len(antenna_indices) == 0:
            if antennas==all:
                antenna_indices = range(n_ants)
            
        return antenna_indices

    def beam_write_int(self, device_name, data, offset=0, beams=all, frequencies=all, beam_indices=[], frequency_indices=[]):
        """Writes data to all devices associated with specified beam"""
        #get all fpgas, bfs, locations associated with this beam 
        targets = self.beam_frequency2location_fpga_bf(beams, frequencies, beam_indices, frequency_indices)
        
        for target in targets:
            name = '%s%s_%s' %(self.config['bf_register_prefix'], target['bf'], device_name)
            #pretend to write if no FPGA
            if self.config.simulate == True:
                print 'dummy write to %s, %s at offset %i'%(target['fpga'], name, offset)
                pass
            else:
                target['fpga'].write_int(device_name=name, integer=data[0], offset=offset)
    
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
            print 'unknown destination: %s' %(destination)
           
        if write == 'on':
            control = control | (0x00000001 << id)
        if read == 'on':
            control = control | (id << 16) 
        return control

    #untested
    #TODO ensure this function call is monotonic due to potential race conditions
    def bf_write_int(self, destination, data, offset=0, beams=all, beam_indices=[], antennas=None, frequencies=None):
        """write to various destinations in the bf block for a particular beam"""

        if antennas==None and frequencies!=None:
            print 'bf_write_int: cannot write to frequencies without antennas being specified'

        locations = self.beam2location(beams=beams, beam_indices=beam_indices)
        
        if len(locations) == 0:
            print 'bf_write_int: you must specify a valid beam to write to'
            return

        #disable writes
        print 'bf_write_int: disabling everything' 
        self.beam_write_int('control', [0x0], 0)
        
        if len(data) == 1:

            print 'bf_write_int: setting up data for single data item' 
            #set up the value to be written
            self.beam_write_int('value_in', data, offset)

        #look up control value required to write when triggering write
        control = self.bf_control_lookup(destination, write='on', read='on')
            
        antenna_indices = self.antenna2antenna_indices(antennas=antennas)
        frequency_indices = self.frequency2frequency_indices(frequencies=frequencies)

        #cycle through beams to be written to
        for location in locations:
           
            print 'bf_write_int: setting up location' 
            #set up target stream (location of beam in set )
            self.beam_write_int('stream', [location], 0, beams=beams)

            #go through antennas (normally just one but may be all or none)
            for antenna_index in antenna_indices:
                
                print 'bf_write_int: setting up antenna' 
                #set up antenna register
                self.beam_write_int('antenna', [antenna_index], 0, beams=beams)
               
                #cycle through frequencies (cannot have frequencies without antenna component) 
                for frequency_index in frequency_indices:

                    print 'bf_write_int: setting up frequency' 
                    #set up frequency register
                    self.beam_write_int('frequency', [frequency_index], 0, beams=beams)
                  
                    #we have a vector of data for each frequency 
                    if len(data) > 1:
                        #set up the value to be written
                        self.beam_write_int('value_in', [data[freq_index]], offset, beams=beams)
 
                    #trigger the write
                    self.beam_write_int('control', [control], 0, beams=beams)      

                #if no frequency component, trigger
                if len(frequency_indices) == 0:
                    #trigger the write
                    print 'bf_write_int: triggering for no frequencies' 
                    self.beam_write_int('control', [control], 0, beams=beams)      
            
            #if no antenna component, trigger write
            if len(antenna_indices) == 0:
                #trigger the write
                print 'bf_write_int: triggering for no antennas' 
                self.beam_write_int('control', [control], 0, beams=beams)      
	
#-----------------------------------
#  Interface for standard operation
#-----------------------------------

    
    def initialise(self, set_cal = True, config_output = True, send_spead = True):
        """Initialises the system and checks for errors."""
        
	#disable all beam
        print 'initialise: disabling all beams'
        self.beam_disable(all)
	
	#TODO need small sleep here as heaps flush
	       
#        if self.config.simulate == False: 
#            if self.tx_status_get(): self.tx_stop()
#        else:
        #print 'initialise: simulating stopping transmission'

        self.spead_config_output()
        self.config_udp_output()

#        if set_cal: self.cal_set_all()
#        else: self.syslogger.info('Skipped calibration config of beamformer.')

#        if send_spead:
#            self.spead_issue_all()

        self.syslogger.info("Beamformer initialisation complete.")
    
    def tx_start(self):
        """Start outputting SPEAD products. Only works for systems with 10GbE output atm.""" 
        if self.config['out_type'] == '10gbe':

            if self.config.simulate == True:
                print 'tx_start: dummy enabling 10Ge output for beamformer'
            else:
                self.c.xeng_ctrl_set_all(beng_out_enable = True)

            self.syslogger.info("Beamformer output started.")
        else:
            self.syslogger.error('Sorry, your output type is not supported. Could not enable output.')
            #raise RuntimeError('Sorry, your output type is not supported.')

    def tx_stop(self, spead_stop=True):
        """Stops outputting SPEAD data over 10GbE links."""
        if self.config['out_type'] == '10gbe':
            if self.config.simulate == True:
                print 'tx_stop: dummy disabling 10Ge output for beamformer'
            else:
                self.c.xeng_ctrl_set_all(beng_out_enable = False)

            self.syslogger.info("Beamformer output paused.")
#            if spead_stop:
#                if self.config.simulate == True:
#                    print 'tx_stop: dummy ending SPEAD stream'
#                else:
#                    tx_temp = spead.Transmitter(spead.TransportUDPtx(self.config['bf_rx_meta_ip_str'], self.config['bf_rx_udp_port']))
#                    tx_temp.end()
#                self.syslogger.info("Sent SPEAD end-of-stream notification.")
#            else:
#                self.syslogger.info("Did not send SPEAD end-of-stream notification.")
        else:
            #raise RuntimeError('Sorry, your output type is not supported.')
            self.syslogger.warn("Sorry, your output type is not supported. Cannot disable output.")
    
    #untested
    def tx_status_get(self):
        """Returns boolean true/false if the beamformer is currently outputting data. Currently only works on systems with 10GbE output."""
        if self.config['out_type']!='10gbe': 
            self.syslogger.warn("This function only works for systems with 10GbE output!")
            return False
        rv=True
        stat=self.c.xeng_ctrl_get_all()
        
        for xn,xsrv in enumerate(self.c.xsrvs):
            if stat[xn]['beng_out_enable'] != True or stat[xn]['gbe_out_rst']!=False: rv=False
        self.syslogger.info('Beamformer output is currently %s'%('enabled' if rv else 'disabled'))
        return rv

    def config_udp_output(self, beams=all, dest_ip_str=None, dest_port=None):
        """Configures the destination IP and port for B engine outputs. dest_port and dest_ip are optional parameters to override the config file defaults."""
        beam_indices = self.beam2index(beams)            

        for beam_index in beam_indices:

            if dest_ip_str==None:
                dest_ip_str=self.config['bf_rx_udp_ip_str_beam%i'%(beam_index)][0]
            else:
                self.config['bf_rx_udp_ip_str_beam%i' %(beam_index)]=dest_ip_str
                self.config['bf_rx_udp_ip_beam%i' %(beam_index)]=struct.unpack('>L',socket.inet_aton(dest_ip_str))[0]
                self.config['bf_rx_meta_ip_str_beam%i' %(beam_index)]=dest_ip_str
                self.config['bf_rx_meta_ip_beam%i' %(beam_index)]=struct.unpack('>L',socket.inet_aton(dest_ip_str))[0]

            if dest_port==None:
                dest_port=self.config['bf_rx_udp_port_beam%i' %(beam_index)]
            else:
                self.config['bf_rx_udp_port_beam%i' %(beam_index)]=dest_port

            beam_offset = self.config['bf_location_beam%i'%(beam_index)]

            dest_ip = struct.unpack('>L',socket.inet_aton(dest_ip_str))[0]

            self.beam_write_int('dest', data=[dest_ip], offset=(beam_offset*2), beams=beams)                     
            self.beam_write_int('dest', data=[dest_port], offset=(beam_offset*2+1), beams=beams)                     
            #each beam output from each beamformer group can be configured differently
            self.syslogger.info("Beam %s configured to %s:%i." % (beams, dest_ip_str, dest_port))

    def beam_enable(self, beams=all):
        """Enables output of data from specified beam"""

        #write to the filter module, ignoring antenna and frequency destinations
        self.bf_write_int(destination='filter', data=[0x1], offset=0x0, beams=beams)  

    def beam_disable(self, beams=all):
        """Disables output of specified beam data"""
        
        #write to the filter module, ignoring antenna and frequency destinations
        self.bf_write_int(destination='filter', data=[0x0], offset=0x0, beams=beams)  

#   CALIBRATION 

    def cal_set_all(self, init_poly = [], init_coeffs = []):
        """Initialise all antennas for all beams' calibration factors to given polynomial. If no polynomial or coefficients are given, use defaults from config file."""

    #untested
    #TODO many beams and antennas
    def cal_default_get(self, beam, antenna, beam_index=[]):
        "Fetches the default calibration configuration from the config file and returns a list of the coefficients for a given beam and antenna." 

        if len(beam_index) == 0:
            beam_index = self.beam2index(beam)

        n_coeffs = self.config['n_chans']

        if self.config['bf_cal_default'] == 'coeffs':
            calibration = self.config['bf_cal_coeffs_beam%i_input%i'%(beam_index, input_n)]

        elif self.config['bf_cal_default'] == 'poly':
            poly = self.config['bf_cal_poly_beam%i_input%i' %(beam_index, input_n)]
            calibration = numpy.polyval(poly, range(self.config['n_chans']))
            if self.config['bf_cal_type'] == 'complex':
                calibration = [cal+0*1j for cal in calibration]
        else: 
            raise RuntimeError("Your cal type, %s, is not understood." % self.config['bf_cal_type'])
                
        if len(calibration) != n_coeffs:
            raise RuntimeError("Something's wrong. I have %i calibration coefficients when I should have %i." % (len(calibration), n_coeffs))
        return calibration

    def cal_spectrum_get(self, beams, beam_indices, input_n):
        """Retrieves the calibration settings currently programmed in all bengines for the given beam and antenna. Returns an array of length n_chans."""

    #untested
    def cal_data_set(self, beams, beam_indices, ants, ant_indices, frequencies, data):
        """Set a given beam and antenna calibration setting to given value"""

        for index, datum in enumerate(data):

            datum_real = numpy.real(datum)
            datum_imag = numpy.imag(datum)        

            if numpy.max(datum_real) > ((2**15)-1) or numpy.min(datum_real)<-((2**15)-1):
                print 'beamformer calibration values out of real range'
            if numpy.max(datum_imag) > ((2**15)-1) or numpy.min(datum_imag)<-((2**15)-1):
                print 'beamformer calibration values out of imaginary range'
            #pack real and imaginary values
            values[index] = (numpy.uint32(datum_real) << 16) | (numpy.uint32(datum_imag) | 0x0000FFFF)
     
        bf_write_int('calibrate', values, 0, beams=beams, beam_indices=beam_indices, antennas=ants, frequencies=frequencies)
    
    #untested
    def cal_spectrum_set(self, beams, beam_indices, ants, init_coeffs = [], init_poly = []):
        """Set given beam and antenna calibration settings to given co-efficients."""

        n_coeffs = self.config['n_chans'] 
        beam  = self.beam2index(beam_name_str)
        
        if init_coeffs == [] and init_poly == []: 
            coeffs = self.bf_cal_default_get(beam=beams, beam_indices=beam_indices, antenna=ants)
        elif len(init_coeffs) == n_coeffs:
            coeffs = init_coeffs
        elif len(init_coeffs)>0: 
            raise RuntimeError ('You specified %i coefficients, but there are %i cal coefficients in this design.'%(len(init_coeffs),n_coeffs))
        else:
            coeffs = numpy.polyval(init_poly, range(self.config['n_chans']))
        
        if self.config['bf_cal_type'] == 'scalar':
            coeffs = numpy.real(coeffs) 
        elif self.config['eq_type'] == 'complex':
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
        n_chans = self.config('n_chans')
        bandwidth = self.config('adc_clck')/2
        freqs = range(0, bandwidth, bandwidth/n_chans)

        cal_data_set(beam_name_str, ant_str, freqs, coeffs)

	#-----------
	#   SPEAD
	#-----------

    def time_from_spead(self, spead_time):
        """Returns the unix time UTC equivalent to the input packet timestamp. Does not account for wrapping timestamp counters."""
        return self.config['sync_time']+float(spead_time)/float(self.config['spead_timestamp_scale_factor'])
        
    def spead_timestamp_from_time(self,time_seconds):
        """Returns the packet timestamp from a given UTC system time (seconds since Unix Epoch). Accounts for wrapping timestamp."""
        return int((time_seconds - self.config['sync_time'])*self.config['spead_timestamp_scale_factor'])%(2**(self.config['spead_flavour'][1]))
 
    def spead_config_output(self):
        '''Sets up configuration registers controlling SPEAD output'''
         
        #set up data and timestamp ids
        if self.config.simulate == True:
            print 'spead_config_output: dummy write to beng_data_id on all x engines'
            print 'spead_config_output: dummy write to beng_time_id on all x engines'
        else:
		#TODO data id should increment for beams
            self.c.xwrite_int_all('beng_data_id', (0x000000 | 0x00B000) #data id
            self.c.xwrite_int_all('beng_time_id', (0x800000 | 5632) ) #same timestamp id as for correlator
        
        n_beams = self.config['bf_n_beams']
        bf_prefix = self.config['bf_register_prefix']
        n_ants = self.config['n_ants']
        bf_be_per_fpga = self.config['bf_be_per_fpga']        

        #go through all beams
        for beam in range(n_beams):
            location = self.config['bf_location_beam%i'%(beam)]        
            beam_id = beam

            #TODO cater for not whole range 
            bf_indices = range(n_ants * bf_be_per_fpga)
 
            if self.config.simulate == False:
                beam_fpgas = self.c.xfpgas
            else:
                beam_fpgas = self.c.xsrvs

            for index in range(len(bf_indices)):
                bf_index = bf_indices[index]
                fpga = beam_fpgas[int(bf_index/bf_be_per_fpga)] #truncate
                bf = bf_index%bf_be_per_fpga
                bf_config_reg = '%s%i_cfg%i'%(bf_prefix, bf, location)
                offset = index #offset in heap depends on frequency band which increases linearly through fpga and bf
                
                bf_config = (beam_id << 16) & 0xffff0000 | (len(bf_indices) << 8) & 0x0000ff00 | offset & 0x000000ff  
                if self.config.simulate == True: 
                    print 'spead_config_output: dummy write of 0x%x to %s:%s'%(bf_config, fpga, bf_config_reg)
                else:
                    fpga.write_int(bf_config_reg, bf_config, 0)

    def spead_labelling_issue(self):
        """Issues the SPEAD metadata packets describing the labelling/location/connections of the system's analogue inputs."""

        self.spead_ig.add_item(name="input_labelling",id=0x100E,
            description="The physical location of each antenna connection.",
            init_val=numpy.array([(ant_str,input_n,lru,feng_input) for (ant_str,input_n,lru,feng_input) in self.adc_lru_mapping_get()]))

#        self.spead_ig.add_item(name="crosspol_ordering",id=0x100D,
#            description="The output ordering of the cross-pol terms. Packed as a pair of characters, pol1,pol2.",
#            shape=[self.config['n_stokes'],self.config['n_pols']],fmt=spead.mkfmt(('c',8)),
#            init_val=[[bl[0],bl[1]] for bl in self.get_crosspol_order()])
        self.spead_tx.send_heap(self.spead_ig.get_heap())
        self.syslogger.info("Issued SPEAD metadata describing baseline labelling and input mapping to %s:%i."%(self.config['rx_meta_ip_str'],self.config['rx_udp_port']))


    def spead_static_meta_issue(self):
        """ Issues the SPEAD metadata packets containing the payload and options descriptors and unpack sequences."""
        #tested ok corr-0.5.0 2010-08-07

        self.spead_ig.add_item(name="adc_clk",id=0x1007,
            description="Clock rate of ADC (samples per second).",
            shape=[],fmt=spead.mkfmt(('u',64)),
            init_val=self.config['adc_clk'])

        #TODO
#        self.spead_ig.add_item(name="n_beams",id=0x,
#            description="The total number of baselines in the data product.",
#            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
#            init_val=self.config['n_bls'])
#
        self.spead_ig.add_item(name="n_chans",id=0x1009,
            description="The total number of frequency channels present in any integration.",
            shape=[], fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['n_chans'])

        self.spead_ig.add_item(name="n_ants",id=0x100A,
            description="The total number of dual-pol antennas in the system.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['n_ants'])

        #TODO
#        self.spead_ig.add_item(name="n_bengs",id=0x,
#            description="The total number of B engines for this beam-group.",
#            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
#            init_val=self.config['n_xeng'])

        self.spead_ig.add_item(name="center_freq",id=0x1011,
            description="The center frequency of the DBE in Hz, 64-bit IEEE floating-point number.",
            shape=[],fmt=spead.mkfmt(('f',64)),
            init_val=self.config['center_freq'])

        self.spead_ig.add_item(name="bandwidth",id=0x1013,
            description="The analogue bandwidth of the digitally processed signal in Hz.",
            shape=[],fmt=spead.mkfmt(('f',64)),
            init_val=self.config['bandwidth'])
        
        #1015/1016 are taken (see time_metadata_issue below)

        self.spead_ig.add_item(name="requant_bits",id=0x1020,
            description="Number of bits after requantisation in the F engines (post FFT and any phasing stages).",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['feng_bits'])

        self.spead_ig.add_item(name="feng_pkt_len",id=0x1021,
            description="Payload size of 10GbE packet exchange between F and X engines in 64 bit words. Usually equal to the number of spectra accumulated inside X engine. F-engine correlator internals.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['10gbe_pkt_len'])

#TODO ADD VERSION INFO!

        #TODO
#        self.spead_ig.add_item(name="b_per_fpga",id=0x,
#            description="Number of B engines per FPGA.",
#            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
#            init_val=self.config['x_per_fpga'])

        #TODO
        self.spead_ig.add_item(name="ddc_mix_freq",id=0x1043,
            description="Digital downconverter mixing freqency as a fraction of the ADC sampling frequency. eg: 0.25. Set to zero if no DDC is present.",
            shape=[],fmt=spead.mkfmt(('f',64)),
            init_val=self.config['ddc_mix_freq'])

#        self.spead_ig.add_item(name="ddc_bandwidth",id=0x1044,
#            description="Digitally processed bandwidth, post DDC, in Hz.",
#            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
#            init_val=self.config['bandwidth']) #/self.config['ddc_decimation']) config's bandwidth is already divided by ddc decimation

#0x1044 should be ddc_bandwidth, not ddc_decimation.
#        self.spead_ig.add_item(name="ddc_decimation",id=0x1044,
#            description="Frequency decimation of the digital downconverter (determines how much bandwidth is processed) eg: 4",
#            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
#            init_val=self.config['ddc_decimation'])

        self.spead_ig.add_item(name="adc_bits",id=0x1045,
            description="ADC quantisation (bits).",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['adc_bits'])

        self.spead_tx.send_heap(self.spead_ig.get_heap())
        self.syslogger.info("Issued misc SPEAD metadata to %s:%i."%(self.config['rx_meta_ip_str'],self.config['rx_udp_port']))

    def spead_time_meta_issue(self):
        """Issues a SPEAD packet to notify the receiver that we've resync'd the system, acc len has changed etc."""

        #sync time
        self.spead_ig.add_item(name='sync_time',id=0x1027,
            description="Time at which the system was last synchronised (armed and triggered by a 1PPS) in seconds since the Unix Epoch.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.config['sync_time'])

        #scale factor for timestamp
        self.spead_ig.add_item(name="scale_factor_timestamp",id=0x1046,
            description="Timestamp scaling factor. Divide the SPEAD data packet timestamp by this number to get back to seconds since last sync.",
            shape=[],fmt=spead.mkfmt(('f',64)),
            init_val=self.config['spead_timestamp_scale_factor'])

        self.spead_tx.send_heap(self.spead_ig.get_heap())
        self.syslogger.info("Issued SPEAD timing metadata to %s:%i."%(self.config['rx_meta_ip_str'],self.config['rx_udp_port']))

    #TODO
#    def spead_cal_meta_issue(self):
#        """Issues a SPEAD heap for the calibration settings."""

    def spead_eq_meta_issue(self):
        """Issues a SPEAD heap for the RF gain and EQ settings."""
        #RF
        if self.config['adc_type'] == 'katadc':
            for input_n,ant_str in enumerate(self.config._get_ant_mapping_list()):
                self.spead_ig.add_item(name="rf_gain_%i"%(input_n),id=0x1200+input_n,
                    description="The analogue RF gain applied at the ADC for input %i (ant %s) in dB."%(input_n,ant_str),
                    shape=[],fmt=spead.mkfmt(('f',64)),
                    init_val=self.config['rf_gain_%i'%(input_n)])

        #equaliser settings
        for in_n,ant_str in enumerate(self.config._get_ant_mapping_list()):
            self.spead_ig.add_item(name="eq_coef_%s"%(ant_str),id=0x1400+in_n,
                description="The unitless per-channel digital scaling factors implemented prior to requantisation, post-FFT, for input %s. Complex number real,imag 32 bit integers."%(ant_str),
                shape=[self.config['n_chans'],2],fmt=spead.mkfmt(('u',32)),
                init_val=[[numpy.real(coeff),numpy.imag(coeff)] for coeff in self.eq_spectrum_get(ant_str)])

        self.spead_tx.send_heap(self.spead_ig.get_heap())
        self.syslogger.info("Issued SPEAD EQ metadata to %s:%i."%(self.config['rx_meta_ip_str'],self.config['rx_udp_port']))

    #untested
    def spead_data_descriptor_issue(self):
        """ Issues the SPEAD data descriptors for the HW 10GbE output, to enable receivers to decode the data."""
        #tested ok corr-0.5.0 2010-08-07

        #timestamp
        self.spead_ig.add_item(name=('timestamp'), id=0x1016,
            description='Timestamp of start of this block of data. uint counting multiples of ADC samples since last sync (sync_time, id=0x1027). Divide this number by timestamp_scale (id=0x1046) to get back to seconds since last sync when this integration was actually started. Note that the receiver will need to figure out the centre timestamp of the accumulation (eg, by adding half of int_time, id 0x1016).',
            shape=[], fmt=spead.mkfmt(('u',spead.ADDRSIZE)),init_val=0)
 
        #data item
        self.spead_ig.add_item(name=("beng_raw"), id=0x00B000,
            description="Raw data for bengines in the system.  Frequencies are assembled from lowest frequency to highest frequency. Frequencies come in blocks of values in time order where the number of samples in a block is given by xeng_acc_len (id 0x101F). Each value is a complex number -- two (real and imaginary) signed integers.",
            ndarray=(numpy.dtype(numpy.int32),(self.config['n_chans'],self.config['n_bls'],2)))
            
        self.spead_tx.send_heap(self.spead_ig.get_heap())
        self.syslogger.info("Issued SPEAD data descriptor to %s:%i."%(self.config['rx_meta_ip_str'],self.config['rx_udp_port']))
    
    def spead_issue_all(self):
        """Issues all SPEAD metadata."""
        self.spead_data_descriptor_issue()
        self.spead_static_meta_issue()
        self.spead_time_meta_issue()
        self.spead_eq_meta_issue()
        self.spead_labelling_issue()

