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
2013-03-01 AM calibration 
\n"""

import corr, time, sys, numpy, os, logging, katcp, struct, construct, socket, spead
import inspect

class fbfException(Exception):
    def __init__(self, errno, msg, trace=None, logger=None):
        self.args = (errno, msg)
        self.errno = errno
        self.errmsg = msg
        self.__trace__ = trace
        if logger: logger.error('BFError: %s\n%s' % (msg,trace))

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

        self.spead_initialise()
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
	"""Read beamformer parameter from config dictionary"""
        try:
            value = self.config[param]
        except KeyError as ke:
            self.syslogger.error('get_param: error getting value of self.config[%s]'%ke)
            raise # simply raise to the calling function
        except Exception as err:
            # Issues a message at the ERROR level and addes exception information to the log message
            self.syslogger.exception(err.__class__)
            raise
        return value

    def set_param(self, param, value):
        try:
            self.config[param] = value
        except KeyError as ke:
            self.syslogger.error('set_param: error setting value of self.config[%s]'%ke)
            raise
        except Exception as err:
            # Issues a message at the ERROR level and addes exception information to the log message
            self.syslogger.exception(err.__class__)
            raise

    def get_beam_param(self, beams, param):

        values = []

        beams = self.beams2beams(beams)

        beam_indices = self.beam2index(beams)
        if len(beam_indices) == 0:
            raise fbfException(1, 'Error locating beams', \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

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
            raise fbfException(1, 'Beam vector must be same length as value vector if passing many values', \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

        beam_indices = self.beam2index(beams)
        if len(beam_indices) == 0:
            raise fbfException(1, 'Error locating beams', \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

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
                raise fbfException(1, 'Error accessing self.c.xfpgas', \
                                   'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                                   self.syslogger)
        else:
            try: 
                all_fpgas = self.c.xsrvs
            except:
                raise fbfException(1, 'Error accessing self.c.xsrvs', \
                                   'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                                   self.syslogger)

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

    def ants2ants(self, ant_strs = all):
        """expands all, None etc into valid antenna strings. Checks for valid antenna strings"""

        ants = []
        if ant_strs == None:
            return ants
        all_ants = self.config._get_ant_mapping_list()

        if ant_strs == all:
            ants = all_ants
            return ants

        for ant_str in ant_strs:
            if(all_ants.count(ant_str) == 0):
                raise fbfException(1, '%s not found in antenna mapping'%(ant_str) , \
                                   'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                                   self.syslogger)
            else:
                ants.append(ant_str)

        return ants

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
                    raise fbfException(1, '%s not found in our system'%beam, \
                                       'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                                       self.syslogger)

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

            if index < 0 or index > len(all_fpgas)-1:
                raise fbfException(1, 'FPGA index calculated out of range', \
                                   'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                                   self.syslogger)

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
            raise fbfException(1, 'FFT bin/s out of range', \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

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
            raise fbfException(1, 'FFT bin/s out of range', \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

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
            raise fbfException(1, 'fft_bins out of range 0 -> %d' %(n_chans-1), \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

        bandwidth = self.get_param('adc_clk')/2

	for fft_bin in fft_bins:
	    frequencies.append((float(fft_bin)/n_chans)*bandwidth)

	return frequencies

    def frequency2fpga_bf(self, frequencies=all, fft_bins=[], unique=False):
        """returns a list of dictionaries {fpga, beamformer_index} based on frequency. unique gives only unique values"""
        locations = []
    
        if unique != True and unique != False:
            raise fbfException(1, 'unique must be True or False', \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

        if len(fft_bins) == 0:
            fft_bins = self.frequency2fft_bin(frequencies)

        fpgas = self.frequency2fpgas(fft_bins=fft_bins)
        bfs = self.frequency2bf_label(fft_bins=fft_bins)

        if len(fpgas) != len(bfs):
            raise fbfException(1, 'fpga and bfs associated with frequencies not the same length', \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)
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

        antenna_indices = []
        n_ants = self.config['n_ants']

        if len(antenna_indices) == 0:
            if antennas==all:
                antenna_indices.extend(range(n_ants))
            #map antenna strings to inputs
            else:
                for ant in antennas:
                    antenna_indices.append(self.c.map_ant_to_input(ant))    
    
        return antenna_indices

    def write_int(self, device_name, data, offset=0, frequencies=all, fft_bins=[]):
        """Writes data to all devices on all bfs in all fpgas associated with the frequencies specified"""
        
        #get all fpgas, bfs associated with frequencies specified 
        targets = self.frequency2fpga_bf(frequencies, fft_bins, unique=True)
        
        if len(data) > 1 and len(targets) != len(data): 
            raise fbfException(1, 'Many data but size (%d) does not match length of targets (%d)'%(len(data), len(targets)), \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

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
        values = []
        
        #get all unique fpgas, bfs associated with the specified frequencies 
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
                    raise fbfException(1, 'Error reading from %s:%s offset %i'%(target['fpga'], name, offset), \
                                       'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                                       self.syslogger)

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
            raise fbfException(1, 'Invalid destination: %s'%destination, \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

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
                raise fbfException(1, 'Need to specify an antenna when reading from calibrate block', \
                                   'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                                   self.syslogger)
            if frequencies==None and len(fft_bins)==0:
                raise fbfException(1, 'Need to specify a frequency or fft bin when reading from calibrate block', \
                                   'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                                   self.syslogger)
        elif destination == 'filter':
            if antennas != None:
                raise fbfException(1, 'Can''t specify antenna when reading from filter block', \
                                   'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                                   self.syslogger)
        else:
            raise fbfException(1, 'Invalid destination: %s'%destination, \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

        if len(fft_bins) == 0:
            fft_bins = self.frequency2fft_bin(frequencies)

        location = self.beam2location(beams=beam)
        
        if len(location) == 0:
            raise fbfException(1, 'You must specify a valid beam to write to', \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

        if len(location) > 1:
            raise fbfException(1, 'You can only read from one beam at a time', \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

        #look up control value required to read 
        control = self.bf_control_lookup(destination, write='off', read='on')
        print 'bf_read_int: disabling writes, setting up reads' 
        self.write_int('control', [control], offset=0, fft_bins=fft_bins)
       
        #expand, check and convert to input indices
        antennas = self.ants2ants(antennas)
        antenna_indices = self.antenna2antenna_indices(antennas=antennas)

        print 'bf_read_int: setting up location' 
        #set up target stream (location of beam in set )
        self.write_int('stream', [location[0]], offset=0, fft_bins=fft_bins)

        #go through antennas (normally just one but may be all or none)
        for antenna_index in antenna_indices:

            print 'bf_read_int: setting up antenna' 
            #set up antenna register
            self.write_int('antenna', [antenna_index], 0, fft_bins=fft_bins)

            #cycle through frequencies (cannot have frequencies without antenna component) 
            for index, fft_bin in enumerate(fft_bins):

                print 'bf_read_int: setting up frequency' 
                #set up frequency register
                self.write_int('frequency', [self.frequency2frequency_reg_index(fft_bins=[fft_bin])][0], 0, fft_bins=[fft_bin])

                values.extend(self.read_int('value_out', offset=0, fft_bins=[fft_bin]))
 
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

    def bf_write_int(self, destination, data, offset=0, beams=all, antennas=None, frequencies=None, fft_bins=[]):
        """write to various destinations in the bf block for a particular beam"""

        if destination == 'calibrate':
            if antennas == None:
                raise fbfException(1, 'Need to specify an antenna when writing to calibrate block', \
                                   'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                                   self.syslogger)
            if frequencies == None and len(fft_bins) == 0:
                raise fbfException(1, 'Need to specify a frequency or fft bin when writing to calibrate block', \
                                   'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                                   self.syslogger)
        elif destination == 'filter':
            if antennas != None:
                raise fbfException(1, 'Can''t specify antenna for filter block', \
                                   'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                                   self.syslogger)
        else:
            raise fbfException(1, 'Invalid destination: %s'%destination, \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

        #convert frequencies to list of fft_bins
        if len(fft_bins) == 0:
            fft_bins = self.frequency2fft_bin(frequencies)
    
        #trying to write multiple data but don't have enough frequencies
        if len(data) > 1 and len(fft_bins) != len(data):
            raise fbfException(1, 'data and frequency vector lengths incompatible', \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

        locations = self.beam2location(beams=beams)

        if len(locations) == 0:
            raise fbfException(1, 'You must specify a valid beam to write to', \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

        #disable writes
        print 'bf_write_int: disabling everything' 
        self.write_int('control', [0x0], 0, fft_bins=fft_bins)
        
        if len(data) == 1:

            print 'bf_write_int: setting up data for single data item' 
            #set up the value to be written
            self.write_int('value_in', data, offset, fft_bins=fft_bins)

        #look up control value required to write when triggering write
        control = self.bf_control_lookup(destination, write='on', read='on')
      
        #expand, check and convert to input indices 
        antennas = self.ants2ants(antennas) 
        antenna_indices = self.antenna2antenna_indices(antennas=antennas)

        #cycle through beams to be written to
        for location in locations:
           
            print 'bf_write_int: setting up location' 
            #set up target stream (location of beam in set )
            self.write_int('stream', [location], 0, fft_bins=fft_bins)

            #go through antennas (normally just one but may be all or None)
            for antenna_index in antenna_indices:
                
                #if no frequency component (i.e all frequencies for this antenna)
                print 'bf_write_int: setting up antenna' 
                #set up antenna register
                self.write_int('antenna', [antenna_index], 0, fft_bins=fft_bins)
               
                #cycle through frequencies (cannot have frequencies without antenna component) 
                for index, fft_bin in enumerate(fft_bins):
                    
                    print 'bf_write_int: setting up frequency' 
                    #set up frequency register on bf associated with fft_bin being processed
                    self.write_int('frequency', [self.frequency2frequency_reg_index(fft_bins=[fft_bin])][0], 0, fft_bins=[fft_bin])
                  
                    #we have a vector of data (one for every frequency)
                    if len(data) > 1:
                        #set up the value to be written
                        print 'bf_write_int: setting up one of multiple data values' 
                        self.write_int('value_in', [data[index]], 0, fft_bins=[fft_bin])
 
                    #trigger the write
                    print 'bf_write_int: triggering antenna, frequencies' 
                    self.write_int('control', [control], 0, fft_bins=[fft_bin])      

                #if no frequency component, trigger
                if len(fft_bins) == 0:
                    #trigger the write
                    print 'bf_write_int: triggering for no antenna but no frequencies' 
                    self.write_int('control', [control], 0, fft_bins=fft_bins)      
            
            #if no antenna component, trigger write
            if len(antenna_indices) == 0:
                #trigger the write
                print 'bf_write_int: triggering for no antennas (and no frequencies)' 
                self.write_int('control', [control], 0, fft_bins=fft_bins)      

    def cf_bw2fft_bins(self, centre_frequency, bandwidth):
        """returns fft bins associated with provided centre_frequency and bandwidth"""
        bins = []

        adc_clk = self.config['adc_clk']
        n_chans = self.config['n_chans']

        #TODO spectral line mode systems??
        if (centre_frequency-bandwidth/2) < 0 or (centre_frequency+bandwidth/2) > adc_clk/2:
            raise fbfException(1, 'Band specified out of range of our system', \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

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

                    #configure disabled beamformers to output to HEAP 0 HEAP size of 0, offset 0
                    bf_config = ((0 << 16) & 0xffff0000 | (0 << 8) & 0x0000ff00 | 0 & 0x000000ff) 
                    self.write_int('cfg%i'%beam_index, [bf_config], 0, fft_bins=disabled_fft_bins)
                
                #get frequency_indices associated with enabled parts of beams
                enabled_fft_bins = self.get_enabled_fft_bins(beam)
        
                #generate vector of values that will match the number of bfs in the list
                fpga_bf_e = self.frequency2fpga_bf(fft_bins=enabled_fft_bins, unique=True)
                bf_config = []
                for offset in range(len(fpga_bf_e)):
                    bf_config.append(((beam_index+1) << 16) & 0xffff0000 | (len(fpga_bf_e) << 8) & 0x0000ff00 | offset & 0x000000ff)
                
                if self.config.simulate == True:
                    print 'configuring included bfs'
                self.write_int('cfg%i'%beam_index, bf_config, 0, fft_bins=enabled_fft_bins)

                if self.config.simulate == True:
                    print 'enabling included bfs'
                #lastly enable those parts
                self.bf_write_int(destination='filter', data=[0x1], offset=0x0, beams=beam, fft_bins = enabled_fft_bins)  
                self.syslogger.info('Output for %s started' %(beam))
        else:
            raise fbfException(1, 'Sorry, your output type is not supported. Could not enable output.', \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

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
            raise fbfException(1, 'Sorry, your output type is not supported. Cannot disable output for beam %s.'%beam, \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

    def tx_status_get(self, beam):
        """Returns boolean true/false if the beamformer is currently outputting data. Currently only works on systems with 10GbE output."""

	if self.get_param('out_type')!='10gbe': 
            raise fbfException(1, 'This function only works for systems with 10GbE output!', \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

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
	        cf = self.get_beam_param(beam, 'centre_frequency')
	    else:
		cf = centre_frequency

	    if bandwidth == None:
		b = self.get_beam_param(beam, 'bandwidth')
	    else:
		b = bandwidth

	    if ((cf-b/2) < 0) or ((cf+b/2) > max_bandwidth):
                raise fbfException(1, 'Passband settings specified for beam %s out of range 0->%iMHz'%(beam, max_bandwidth/1000000), \
                                   'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                                   self.syslogger)

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
        bfs = self.frequency2bf_index(fft_bins=fft_bins, unique=True)
	bf_bandwidth = self.get_bf_bandwidth()
	fft_bin_bandwidth = self.get_fft_bin_bandwidth()

	#calculate start frequency accounting for frequency specified in centre of bin
	start_frequency = min(bfs)*bf_bandwidth-fft_bin_bandwidth/2
	centre_frequency = start_frequency+bf_bandwidth*(float(len(bfs))/2)

	beam_bandwidth = len(bfs) * bf_bandwidth
	
        return centre_frequency, beam_bandwidth
    
    def get_n_chans(self, beam):
        """gets the number of active channels for the specified beam"""       
 
	fft_bin_bandwidth = self.get_fft_bin_bandwidth()
        cf,bw = get_passband(beam)

        n_chans = bw/fft_bin_bandwidth

        return n_chans
        

#   CALIBRATION 

    #untested
    def cal_set_all(self, beams, init_poly = [], init_coeffs = []):
        """Initialise all antennas for all specified beams' calibration factors to given polynomial. If no polynomial or coefficients are given, use defaults from config file."""

        beams = self.beams2beams(beams)

        #get all antenna input strings
        ant_strs = self.ants2ants(all)

        #go through all beams specified
        for beam in beams:

            #go through all antennas for beams
            for ant_str in ant_strs:
                self.cal_spectrum_set(beam=beam, ant_str=ant_str, init_coeffs=init_coeffs, init_poly=init_poly)
                
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
            raise fbfException(1, 'Your default beamformer calibration type, %s, is not understood.'%bf_cal_default, \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

        if len(calibration) != n_coeffs:
            raise fbfException(1, 'Something\'s wrong. I have %i calibration coefficients when I should have %i.'%(len(calibration), n_coeffs), \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)
        return calibration

    def cal_spectrum_get(self, beam, ant_str):
        """Retrieves the calibration settings currently programmed in all bengines for the given beam and antenna. Returns an array of length n_chans."""

	values = []
        data = self.bf_read_int(beam=beam, destination='calibrate', offset=0, antennas=[ant_str], frequencies=all) 
        for datum in data:

            datum_real = (numpy.int32(datum & 0xFFFF0000)) >> 16
            datum_imag = (numpy.int32(datum & 0x0000FFFF))       

            #pack real and imaginary values into 32 bit value
            values.append(complex(datum_real, datum_imag))
        
	return values

    def cal_data_set(self, beam, ant_strs, frequencies, data):
        """Set a given beam and antenna calibration setting to given value"""
        values = []

        #convert frequencies to fft indices
        fft_bins = self.frequency2fft_bin(frequencies=frequencies)

        #data length must be 1 or data vector must be same length as frequency vector
        if len(data) != 1 and (len(fft_bins) != len(data)):
            raise fbfException(1, 'Data vector length (%i) and frequency vector length (%i) incompatible'%(len(fft_bins), len(data)), \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

        if max(numpy.real(data)) > ((2**15)-1) or min(numpy.real(data))<-((2**15)-1):
            raise fbfException(1, 'real calibration values out of range', \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)
        if max(numpy.imag(data)) > ((2**15)-1) or min(numpy.imag(data))<-((2**15)-1):
            raise fbfException(1, 'imaginary calibration values out of range', \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

        #convert data
        for datum in data:

            datum_real = numpy.real(datum)
            datum_imag = numpy.imag(datum)        

            #pack real and imaginary values into 32 bit value
            values.append((numpy.int32(datum_real) << 16) | (numpy.int32(datum_imag) & 0x0000FFFF))

        #write final vector to calibrate block
        self.bf_write_int('calibrate', values, offset=0, beams=[beam], antennas=ant_strs, fft_bins=fft_bins)
    
    #untested
    def cal_spectrum_set(self, beam, ant_str, init_coeffs = [], init_poly = []):
        """Set given beam and antenna calibration settings to given co-efficients."""

        #TODO error checking

        n_coeffs = self.get_param('n_chans') 
        
        if init_coeffs == [] and init_poly == []: 
            coeffs = self.cal_default_get(beam=beam, ant_str=ant_str)
        elif len(init_coeffs) == n_coeffs:
            coeffs = init_coeffs
        elif len(init_coeffs) > 0: 
            raise fbfException(1, 'You specified %i coefficients, but there are %i cal coefficients required for this design.'%(len(init_coeffs),n_coeffs), \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)
        else:
            coeffs = numpy.polyval(init_poly, range(n_coeffs))
        
        bf_cal_type = self.get_param('bf_cal_type')
        if bf_cal_type == 'scalar':
            coeffs = numpy.real(coeffs) 
        elif self.get_param('bf_cal_type') == 'complex':
            coeffs = numpy.array(coeffs, dtype = numpy.complex128)
        else:
            raise fbfException(1, 'Sorry, your beamformer calibration type is not supported. Expecting scalar or complex.', \
                               'function %s, line no %s\n' %(__name__, inspect.currentframe().f_lineno), \
                               self.syslogger)

        self.cal_data_set(beam=beam, ant_strs=[ant_str], frequencies=all, data=coeffs)

	#-----------
	#   SPEAD
	#-----------

    def spead_config_basics(self):
        '''Sets up spead item and data values in gateware'''
        
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
    
    def spead_initialise():
        """creates spead transmitters that will be used by the beams in our system"""
            
        #create a spead transmitter for every beam and store in config
        for beam in self.beams2beams(all):
            ip_str = self.get_beam_param(beam, 'rx_meta_ip_str')
            port = self.get_beam_param(beam, 'rx_udp_port')
            self.spead_tx['bf_spead_tx_beam%i'%self.beam2index(beam)] = spead.Transmitter(spead.TransportUDPtx(ip_str, port))
            self.syslogger.info("Created spead transmitter for beam %s. Destination IP = %s, port = " %(beam, ip_str, port))

#TODO
#    def configure_spead_output(self, beam, )
#        """configure destination ip and port for spead metadata"""

    def get_spead_tx(self, beam):
        beam = self.beams2beams(beam)

        beam_index = self.beam2index(beam)
        try:
            spead_tx = self.spead_tx['bf_spead_tx_beam%i'%beam_index]
        except:
            print 'error locating spead_tx for beam %s' %beam
            return
            #TODO proper exception
        return spead_tx

    def send_spead_heap(self, beam, ig):
        """Sends spead item group via transmitter for beam specified"""

        beam = beams2beams(beam)
        spead_tx = self.get_spead_tx(beam)
        send_heap(ig.get_heap())

    def spead_labelling_issue(self, beams=all):
        """Issues the SPEAD metadata packets describing the labelling/location/connections of the system's analogue inputs."""
        beams = self.beams2beams(beams)

        spead_ig=spead.ItemGroup()

        spead_ig.add_item(name="input_labelling",id=0x100E,
            description="The physical location of each antenna connection.",
            init_val=numpy.array([(ant_str,input_n,lru,feng_input) for (ant_str,input_n,lru,feng_input) in self.c.adc_lru_mapping_get()]))
        
        for beam in beams:
            self.send_spead_heap(beam, spead_ig)
            self.syslogger.info("Issued SPEAD metadata describing baseline labelling and input mapping for beam %s" %(beam))

    def spead_static_meta_issue(self, beams=all):
        """ Issues the SPEAD metadata packets containing the payload and options descriptors and unpack sequences."""

        beams = beams2beams(beams)

#        spead stuff that does not care about beam
        spead_ig=spead.ItemGroup()

        spead_ig.add_item(name="adc_clk",id=0x1007,
            description="Clock rate of ADC (samples per second).",
            shape=[],fmt=spead.mkfmt(('u',64)),
            init_val=self.get_param('adc_clk'))

        spead_ig.add_item(name="n_ants",id=0x100A,
            description="The total number of dual-pol antennas in the system.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.get_param('n_ants'))

        spead_ig.add_item(name="n_bengs",id=0x100F,
            description="The total number of B engines in the system.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.get_param('bf_be_per_fpga')*len(self.get_fpgas()))
        
        #1015/1016 are taken (see time_metadata_issue below)
        
        self.spead_ig.add_item(name="xeng_acc_len",id=0x101F,
            description="Number of spectra accumulated inside X engine. Determines minimum integration time and user-configurable integration time stepsize. X-engine correlator internals.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.get_param('xeng_acc_len'))

        spead_ig.add_item(name="requant_bits",id=0x1020,
            description="Number of bits after requantisation in the F engines (post FFT and any phasing stages).",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.get_param('feng_bits'))

        spead_ig.add_item(name="feng_pkt_len",id=0x1021,
            description="Payload size of 10GbE packet exchange between F and X engines in 64 bit words. Usually equal to the number of spectra accumulated inside X engine. F-engine correlator internals.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.get_param('10gbe_pkt_len'))

        self.spead_ig.add_item(name="feng_udp_port",id=0x1023,
            description="Destination UDP port for B engine data exchange.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.get_param('10gbe_port'))

        self.spead_ig.add_item(name="feng_start_ip",id=0x1025,
            description="F engine starting IP address.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.get_param('10gbe_ip'))

#TODO ADD VERSION INFO!

        spead_ig.add_item(name="b_per_fpga",id=0x1047,
            description="The total number of baselines in the data product.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.get_param('bf_be_per_fpga'))

        spead_ig.add_item(name="ddc_mix_freq",id=0x1043,
            description="Digital downconverter mixing freqency as a fraction of the ADC sampling frequency. eg: 0.25. Set to zero if no DDC is present.",
            shape=[],fmt=spead.mkfmt(('f',64)),
            init_val=self.get_param('ddc_mix_freq'))

        spead_ig.add_item(name="adc_bits",id=0x1045,
            description="ADC quantisation (bits).",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.get_param('adc_bits'))
        
        spead_ig.add_item(name="beng_out_bits_per_sample",id=0x1050,
            description="The number of bits per value in the beng output. Note that this is for a single value, not the combined complex value size.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.get_param('bf_bits_out'))

        for beam in beams:
            
            self.send_spead_heap(beam, spead_ig)
            self.syslogger.info("Issued static SPEAD metadata for beam %s" %beam)
    
    def spead_destination_meta_issue(self, beams=all):
        """Issues a SPEAD packet to notify the receiver of changes to destination"""
        
        for beam in beams:
            spead_ig=spead.ItemGroup()
           
            self.spead_ig.add_item(name="rx_udp_port",id=0x1022,
                description="Destination UDP port for B engine output.",
                shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
                init_val=self.get_beam_param(beam, 'rx_udp_port'))

            self.spead_ig.add_item(name="rx_udp_ip_str",id=0x1024,
                description="Destination IP address for B engine output UDP packets.",
                shape=[-1],fmt=spead.STR_FMT,
                init_val=self.get_beam_param(beam, 'rx_udp_ip_str'))

            self.send_spead_heap(beam, spead_ig)
            self.syslogger.info("Issued destination SPEAD metadata for beam %s" %beam)

    def spead_passband_meta_issue(self, beams=all):
        """Issues a SPEAD packet to notify the receiver of changes to passband parameters"""
        
        for beam in beams:
            spead_ig=spead.ItemGroup()
            cf,bw = self.get_passband(beam)
 
            spead_ig.add_item(name="center_freq",id=0x1011,
                description="The center frequency of the DBE in Hz, 64-bit IEEE floating-point number.",
                shape=[],fmt=spead.mkfmt(('f',64)),
                init_val=cf)

            spead_ig.add_item(name="bandwidth",id=0x1013,
                description="The analogue bandwidth of the digitally processed signal in Hz.",
                shape=[],fmt=spead.mkfmt(('f',64)),
                init_val=bw)
            
            spead_ig.add_item(name="n_chans",id=0x1009,
                description="The total number of frequency channels present in any integration.",
                shape=[], fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
                init_val=self.get_n_chans(beam))
            
            self.send_spead_heap(beam, spead_ig)
            self.syslogger.info("Issued passband SPEAD metadata for beam %s" %beam)

    def spead_time_meta_issue(self, beams=all):
        """Issues a SPEAD packet to notify the receiver that we've resync'd the system, acc len has changed etc."""

        beams = beams2beams(beams)       
 
        spead_ig = spead.ItemGroup()
        
        #TODO check if we need this 
        self.spead_ig.add_item(name="int_time",id=0x1016,
            description="Approximate (it's a float!) integration time per accumulation in seconds.",
            shape=[],fmt=spead.mkfmt(('f',64)),
            init_val=self.c.acc_time_get())
        
        #sync time
        spead_ig.add_item(name='sync_time',id=0x1027,
            description="Time at which the system was last synchronised (armed and triggered by a 1PPS) in seconds since the Unix Epoch.",
            shape=[],fmt=spead.mkfmt(('u',spead.ADDRSIZE)),
            init_val=self.get_param('sync_time'))

        #scale factor for timestamp
        spead_ig.add_item(name="scale_factor_timestamp",id=0x1046,
            description="Timestamp scaling factor. Divide the SPEAD data packet timestamp by this number to get back to seconds since last sync.",
            shape=[],fmt=spead.mkfmt(('f',64)),
            init_val=self.get_param('spead_timestamp_scale_factor'))
            
        for beam in beams:
                ig = spead_ig

                self.send_spead_heap(beam, ig)
                self.syslogger.info("Issued SPEAD timing metadata for beam %s" %beam)

    def spead_eq_meta_issue(self, beams=all):
        """Issues a SPEAD heap for the RF gain, EQ settings and calibration settings."""
        
        beams = beams2beams(beams)

        spead_ig = spead.ItemGroup()
    
        #RF
        if self.config['adc_type'] == 'katadc':
            for input_n,ant_str in enumerate(self.c.config._get_ant_mapping_list()):
                spead_ig.add_item(name="rf_gain_%i"%(input_n),id=0x1200+input_n,
                    description="The analogue RF gain applied at the ADC for input %i (ant %s) in dB."%(input_n,ant_str),
                    shape=[],fmt=spead.mkfmt(('f',64)),
                    init_val=self.get_param('rf_gain_%i'%(input_n)))

        #equaliser settings
        for in_n,ant_str in enumerate(self.c.config._get_ant_mapping_list()):
            spead_ig.add_item(name="eq_coef_%s"%(ant_str),id=0x1400+in_n,
                description="The unitless per-channel digital scaling factors implemented prior to requantisation, post-FFT, for input %s. Complex number real,imag 32 bit integers."%(ant_str),
                shape=[self.get_param('n_chans'),2],fmt=spead.mkfmt(('u',32)),
                init_val=[[numpy.real(coeff),numpy.imag(coeff)] for coeff in self.eq_spectrum_get(ant_str)])

        for beam in beams:
            ig = spead_ig

            #calibration settings
            for in_n,ant_str in enumerate(self.c.config._get_ant_mapping_list()):
                ig.add_item(name="beamweight_input%s"%(ant_str),id=0x2000+in_n,
                    description="The unitless per-channel digital scaling factors implemented prior to combining antenna signals during beamforming for input %s. Complex number real,imag 32 bit integers."%(ant_str),
                    shape=[self.get_param('n_chans'),2],fmt=spead.mkfmt(('u',32)),
                    init_val=[[numpy.real(coeff),numpy.imag(coeff)] for coeff in self.cal_spectrum_get(beam, ant_str)])
            
            self.send_spead_heap(beam, ig)
            self.syslogger.info("Issued SPEAD EQ metadata for beam %s" %beam)

    #untested
    def spead_data_descriptor_issue(self, beams=all):
        """ Issues the SPEAD data descriptors for the HW 10GbE output, to enable receivers to decode the data."""
        beams = self.beams2beams(beams)
        
        spead_ig = spead.ItemGroup()

        #timestamp
        spead_ig.add_item(name=('timestamp'), id=0x1016,
            description='Timestamp of start of this block of data. uint counting multiples of ADC samples since last sync (sync_time, id=0x1027). Divide this number by timestamp_scale (id=0x1046) to get back to seconds since last sync when this integration was actually started. Note that the receiver will need to figure out the centre timestamp of the accumulation (eg, by adding half of int_time, id 0x1016).',
            shape=[], fmt=spead.mkfmt(('u',spead.ADDRSIZE)),init_val=0)

        beam_indices = self.beam2index(beams)
        for beam in beams:
            ig = spead_ig
 
            #data item
            ig.add_item(name=beam, id=0xB000,
                description="Raw data for bengines in the system.  Frequencies are assembled from lowest frequency to highest frequency. Frequencies come in blocks of values in time order where the number of samples in a block is given by xeng_acc_len (id 0x101F). Each value is a complex number -- two (real and imaginary) signed integers.",
                ndarray=(numpy.dtype(numpy.int8),(2,self.get_param('n_bls'),2)))
                
            self.send_spead_heap(beam, ig)
            self.syslogger.info("Issued SPEAD data descriptor for beam %s" %beam)
    
    def spead_issue_all(self, beams=all):
        """Issues all SPEAD metadata."""

        self.spead_data_descriptor_issue(beams)
        self.spead_static_meta_issue(beams)
        self.spead_passband_meta_issue(beams)
        self.spead_destination_meta_issue(beams)
        self.spead_time_meta_issue(beams)
        self.spead_eq_meta_issue(beams)
        self.spead_labelling_issue(beams)

