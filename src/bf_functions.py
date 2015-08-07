# /usr/bin/env python
"""
Selection of commonly-used beamformer control functions.

Author: Jason Manley, Andrew Martens, Ruby van Rooyen
"""
"""
Revisions:
2012-10-02 JRM Initial
2013-02-10 AM basic boresight
2013-02-11 AM basic SPEAD
2013-02-21 AM flexible bandwidth
2013-03-01 AM calibration
2013-03-02 RR fbfExceptions
2013-03-05 AM SPEAD metadata
\n"""

import corr, numpy, logging, struct, socket
import spead64_48 as spead
import inspect

class fbfException(Exception):
    def __init__(self, errno, msg, trace=None, logger=None):
        self.args = (errno, msg)
        self.errno = errno
        self.errmsg = msg
        self.__trace__ = trace
        if logger:
            logger.error('BFError: %s\n%s' % (msg, trace))

class fbf:
    """Class for frequency-domain beamformers"""
    def __init__(self, host_correlator, log_level=logging.INFO, simulate=False, optimisations=True):
        self.c = host_correlator

        self.config = self.c.config

        #  simulate operations (and output debug data). Useful for when there is no hardware
        self.config.simulate = simulate
        #  optimisations on writes (that currently expose bugs)
        self.optimisations = optimisations

        self.log_handler = host_correlator.log_handler
        self.syslogger = logging.getLogger('fbfsys')
        self.syslogger.addHandler(self.log_handler)
        self.syslogger.setLevel(log_level)
        self.c.b = self

        self.spead_initialise()
        self.syslogger.info('Beamformer created')

# -----------------------
#  helper functions
# -----------------------

    def get_param(self, param):
        """Read beamformer parameter from config dictionary"""
        try:
            value = self.config[param]
        except KeyError as ke:
            self.syslogger.error('get_param: error getting value of self.config[%s]' % ke)
            raise  # simply raise to the calling function
        except Exception as err:
            #  Issues a message at the ERROR level and adds exception information to the log message
            self.syslogger.exception(err.__class__)
            raise
        return value

    def set_param(self, param, value):
        try:
            self.config[param] = value
        except KeyError as ke:
            self.syslogger.error('set_param: error setting value of self.config[%s]' % ke)
            raise
        except Exception as err:
            # Issues a message at the ERROR level and addes exception information to the log message
            self.syslogger.exception(err.__class__)
            raise

    def get_beam_param(self, beams, param):
        values = []
        beams = self.beams2beams(beams)
        beam_indices = self.beam2index(beams)
        if beam_indices == []:
            raise fbfException(1, 'Error locating beams',
                               'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                               self.syslogger)
        for beam_index in beam_indices:
            values.append(self.get_param('bf_%s_beam%d' % (param, beam_index)))
        # for single item
        if len(values) == 1:
            values = values[0]
        return values

    def set_beam_param(self, beams, param, values):
        beams = self.beams2beams(beams)
        # check vector lengths match up
        if type(values) == list and len(values) != len(beams):
            raise fbfException(1, 'Beam vector must be same length as value vector if passing many values',
                               'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                               self.syslogger)
        beam_indices = self.beam2index(beams)
        if len(beam_indices) == 0:
            raise fbfException(1, 'Error locating beams',
                               'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                               self.syslogger)
        for index, beam_index in enumerate(beam_indices):
            if type(values) == list:
                value = values[index]
            else:
                value = values
            self.set_param('bf_%s_beam%d' % (param, beam_index), value)

    def get_fpgas(self, names=False):
        # if doing dummy load (no correlator), use roach names as have not got fpgas yet
        if self.config.simulate == False and names == False:
            try:
                all_fpgas = self.c.xfpgas
            except:
                raise fbfException(1, 'Error accessing self.c.xfpgas',
                                   'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                                   self.syslogger)
        else:
            try:
                all_fpgas = self.c.xsrvs
            except:
                raise fbfException(1, 'Error accessing self.c.xsrvs',
                                   'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
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
            all_beams.append(self.get_param('bf_name_beam%i' % beam_index))
        return all_beams

    def map_ant_to_input(self, beam, ant_strs=all):
        """maps antenna strings specified to input to beamformer"""
        beam_ants = self.ants2ants(beam=beam, ant_strs=all)
        inputs = []
        for ant_str in ant_strs:
            if self.config.simulate:
                print 'finding index for %s' % ant_str
            inputs.append(beam_ants.index(ant_str))
        return inputs

    def ants2ants(self, beam, ant_strs=all):
        """expands all, None etc into valid antenna strings. Checks for valid antenna strings"""
        ants = []
        if ant_strs == None:
            return []
        all_ants = self.config._get_ant_mapping_list()
        beam = self.beams2beams(beams=beam)[0]
        # construct a list of valid ant_strs for each beam, then check specified ants are in
        if self.config.simulate:
            print 'finding ants for beam %s' % beam
        beam_ants = []
        beam_idx = self.beam2index(beam)
        offset = numpy.mod(beam_idx, 2)
        for n, ant_str in enumerate(all_ants):
            if numpy.mod(n+offset, 2) == 0:
                if self.config.simulate:
                    print 'adding ant %s for beam %s' % (ant_str, beam)
                beam_ants.append(ant_str)
        if ant_strs == all:
            return beam_ants
        for ant_str in ant_strs:
            if beam_ants.count(ant_str) == 0:
                raise fbfException(1, '%s not found in antenna mapping for beam %s' % (ant_str, beam),
                                   'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                                   self.syslogger)
            else:
                ants.append(ant_str)
        return ants

    def beams2beams(self, beams=all):
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
            # weed out beam names that do not occur
            for beam in beams:
                try:
                    all_beams.index(beam)
                    new_beams.append(beam)
                except:
                    raise fbfException(1, '%s not found in our system' % beam, 'function %s, line no %s\n'
                                       % (__name__, inspect.currentframe().f_lineno), self.syslogger)
        return new_beams

    def beam2index(self, beams=all):
        """returns index of beam with specified name"""
        indices = []
        # expand all etc, check for valid names etc
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
        n_chans = self.get_param('n_chans')
        n_chans_per_fpga = n_chans/len(all_fpgas)
        prev_index = -1
        for fft_bin in fft_bins:
            index = numpy.int(fft_bin/n_chans_per_fpga) #floor built in
            if index < 0 or index > len(all_fpgas)-1:
                raise fbfException(1, 'FPGA index calculated out of range',
                                   'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
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
        if max(fft_bins) > n_chans-1 or min(fft_bins) < 0:
            raise fbfException(1, 'FFT bin/s out of range', 'function %s, line no %s\n' %
                               (__name__, inspect.currentframe().f_lineno), self.syslogger)
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
        if max(fft_bins) > n_chans-1 or min(fft_bins) < 0:
            raise fbfException(1, 'FFT bin/s out of range',
                               'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
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
            bandwidth = self.get_param('bandwidth')
            start_freq = 0
            channel_width = bandwidth/n_chans
            for frequency in frequencies:
                frequency_normalised = numpy.mod((frequency-start_freq)+channel_width/2, bandwidth)
                fft_bins.append(numpy.int(frequency_normalised/channel_width))  # conversion to int with truncation
        return fft_bins

    def get_bf_bandwidth(self):
        """Returns the bandwidth for one bf engine"""
        bandwidth = self.get_param('bandwidth')
        bf_be_per_fpga = len(self.get_bfs())
        n_fpgas = len(self.get_fpgas())
        bf_bandwidth = float(bandwidth)/(bf_be_per_fpga*n_fpgas)
        return bf_bandwidth

    def get_bf_fft_bins(self):
        """Returns the number of fft bins for one bf engine"""
        n_chans = self.get_param('n_chans')
        bf_be_per_fpga = len(self.get_bfs())
        n_fpgas = len(self.get_fpgas())
        bf_fft_bins = n_chans/(bf_be_per_fpga*n_fpgas)
        return bf_fft_bins

    def get_fft_bin_bandwidth(self):
        """get bandwidth of single fft bin"""
        n_chans = self.get_param('n_chans')
        bandwidth = self.get_param('bandwidth')
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
            raise fbfException(1, 'fft_bins out of range 0 -> %d' % (n_chans-1), 'function %s, line no %s\n'
                               % (__name__, inspect.currentframe().f_lineno), self.syslogger)
        bandwidth = self.get_param('bandwidth')
        for fft_bin in fft_bins:
            frequencies.append((float(fft_bin)/n_chans)*bandwidth)
        return frequencies

    def frequency2fpga_bf(self, frequencies=all, fft_bins=[], unique=False):
        """
        returns a list of dictionaries {fpga, beamformer_index} based on frequency.
        unique gives only unique values
        """
        locations = []
        if unique != True and unique != False:
            raise fbfException(1, 'unique must be True or False', 'function %s, line no %s\n' %
                               (__name__, inspect.currentframe().f_lineno), self.syslogger)
        if len(fft_bins) == 0:
            fft_bins = self.frequency2fft_bin(frequencies)
        fpgas = self.frequency2fpgas(fft_bins=fft_bins)
        bfs = self.frequency2bf_label(fft_bins=fft_bins)
        if len(fpgas) != len(bfs):
            raise fbfException(1, 'fpga and bfs associated with frequencies not the same length',
                               'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                               self.syslogger)
        else:
            pfpga = []
            pbf = []
            for index in range(len(fpgas)):
                fpga = fpgas[index]
                bf = bfs[index]
                if (unique == False) or (pfpga != fpga or pbf != bf):
                    locations.append({'fpga': fpga, 'bf': bf})
                pbf = bf
                pfpga = fpga
        return locations

    def beam_frequency2location_fpga_bf(self, beams=all, frequencies=all, fft_bins=[], unique=False):
        """returns list of dictionaries {location, fpga, beamformer index} based on beam name, and frequency"""
        indices = []
        # get beam locations
        locations = self.beam2location(beams)
        # get fpgas and bfs
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

    def antenna2antenna_indices(self, beam, ant_strs=all):
        antenna_indices = []
        n_ants = self.get_param('n_ants')
        if ant_strs == all:
            antenna_indices.extend(range(n_ants))
        # map antenna strings to inputs
        else:
            antenna_indices = self.map_ant_to_input(beam=beam, ant_strs=ant_strs)
        return antenna_indices

    def write_int(self, device_name, data, offset=0, frequencies=all, fft_bins=[], blindwrite=False):
        """Writes data to all devices on all bfs in all fpgas associated with the frequencies specified"""
        # TODO work this out properly
        timeout = 1
        # get all fpgas, bfs associated with frequencies specified
        targets = self.frequency2fpga_bf(frequencies, fft_bins, unique=True)
        if len(data) > 1 and len(targets) != len(data):
            raise fbfException(1, 'Many data but size (%d) does not match length of targets (%d)'
                               % (len(data), len(targets)), 'function %s, line no %s\n'
                               % (__name__, inspect.currentframe().f_lineno), self.syslogger)
        bf_register_prefix = self.get_param('bf_register_prefix')
        # if optimisations are enabled and (same data, and multiple targets)
        # write to all targets with the same register name
        if self.optimisations and (len(data) == 1 and len(targets) > 1):
            if self.config.simulate == True:
                print 'optimisations on, single data item, writing in parallel'
            datum = data[0]
            n_bfs = len(self.get_bfs())
            # run through all bfs
            for bf_index in range(n_bfs):
                fpgas = []
                # generate register name
                name = '%s%s_%s' % (bf_register_prefix, bf_index, device_name)
                datum = struct.pack(">I", data[0])
                # find all fpgas to be written to for this bf
                for target in targets:
                    if target['bf'] == bf_index:
                        fpgas.append(target['fpga'])
                if len(fpgas) != 0:
                    if self.config.simulate == True:
                        print 'dummy executing non-blocking request for write to %s on %d fpgas' % (name, len(fpgas))
                    else:
                        nottimedout, rv = corr.corr_functions.non_blocking_request(fpgas=fpgas, timeout=timeout,
                                                                                   request='write',
                                                                                   request_args=[name, offset*4, datum])
                        if nottimedout == False:
                            raise fbfException(1, 'Timeout asynchronously writing 0x%.8x to %s on %d fpgas offset %i'
                                               % (data[0], name, len(fpgas), offset), 'function %s, line no %s\n'
                                               % (__name__, inspect.currentframe().f_lineno), self.syslogger)
                        for k, v in rv.items():
                            if v['reply'] != 'ok':
                                raise fbfException(1, 'Got %s instead of ''ok'' when writing 0x%.8x to %s:%s offset %i'
                                                   % (v['reply'], data[0], k, name, offset), 'function %s, line no %s\n'
                                                   % (__name__, inspect.currentframe().f_lineno), self.syslogger)
        # optimisations off, or (many data, or a single target) so many separate writes
        else:
            if self.config.simulate == True:
                print 'optimisations off or multiple items or single target'
            for target_index, target in enumerate(targets):
                if len(data) == 1 and len(targets) > 1:
                    datum = data[0]
                else:
                    datum = data[target_index]
                if datum < 0:
                    datum_str = struct.pack(">i", datum)
                else:
                    datum_str = struct.pack(">I", datum)
                    name = '%s%s_%s' % (bf_register_prefix, target['bf'], device_name)
                # pretend to write if no FPGA
                if self.config.simulate == True:
                    print 'dummy write of 0x%.8x to %s:%s offset %i' % (datum, target['fpga'], name, offset)
                else:
                    try:
                        if blindwrite:
                            target['fpga'].blindwrite(device_name=name, data=datum_str, offset=offset*4)
                        else:
                            target['fpga'].write(device_name=name, data=datum_str, offset=offset*4)
                    except:
                        raise fbfException(1, 'Error writing 0x%.8x to %s:%s offset %i'
                                           % (datum, target['fpga'], name, offset*4), 'function %s, line no %s\n'
                                           % (__name__, inspect.currentframe().f_lineno), self.syslogger)

    def read_int(self, device_name, offset=0, frequencies=all, fft_bins=[]):
        """Reads data from all devices on all bfs in all fpgas associated with the frequencies specified"""
        values = []
        # get all unique fpgas, bfs associated with the specified frequencies
        targets = self.frequency2fpga_bf(frequencies, fft_bins, unique=True)
        for target_index, target in enumerate(targets):
            name = '%s%s_%s' % (self.get_param('bf_register_prefix'), target['bf'], device_name)
            # pretend to read if no FPGA
            if self.config.simulate == True:
                print 'dummy read from %s:%s offset %i' % (target['fpga'], name, offset)
            else:
                try:
                    values.append(target['fpga'].read_int(device_name=name))
                except:
                    raise fbfException(1, 'Error reading from %s:%s offset %i' % (target['fpga'], name, offset),
                                       'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                                       self.syslogger)
        return values

    def bf_control_lookup(self, destination, write=True, read=True):
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
            raise fbfException(1, 'Invalid destination: %s' % destination,
                               'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                               self.syslogger)
        if write == True:
            control = control | (0x00000001 << id)
        if read == True:
            control = control | (id << 16)
        return control

    def bf_read_int(self, beam, destination, offset=0, antennas=None, frequencies=None, fft_bins=[], blindwrite=True):
        """read from destination in the bf block for a particular beam"""
        values = []
        if destination == 'calibrate':
            if antennas == None:
                raise fbfException(1, 'Need to specify an antenna when reading from calibrate block',
                                   'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                                   self.syslogger)
            if frequencies==None and len(fft_bins) == 0:
                raise fbfException(1, 'Need to specify a frequency or fft bin when reading from calibrate block',
                                   'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                                   self.syslogger)
        elif destination == 'filter':
            if antennas != None:
                raise fbfException(1, 'Can''t specify antenna when reading from filter block',
                                   'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                                   self.syslogger)
        else:
            raise fbfException(1, 'Invalid destination: %s'%destination,
                               'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                               self.syslogger)
        if len(fft_bins) == 0:
            fft_bins = self.frequency2fft_bin(frequencies)
        location = self.beam2location(beams=beam)[0]
        # look up control value required to read
        control = self.bf_control_lookup(destination, write=False, read=True)
        # print 'bf_read_int: disabling writes, setting up reads'
        self.write_int('control', [control], offset=0, fft_bins=fft_bins, blindwrite=blindwrite)
        # expand, check and convert to input indices
        antennas = self.ants2ants(beam, antennas)
        antenna_indices = self.antenna2antenna_indices(beam=beam, ant_strs=antennas)
        # print 'bf_read_int: setting up location'
        # set up target stream (location of beam in set )
        self.write_int('stream', [location], offset=0, fft_bins=fft_bins, blindwrite=blindwrite)
        # go through antennas (normally just one but may be all or none)
        for antenna_index in antenna_indices:
            # print 'bf_read_int: setting up antenna'
            # set up antenna register
            self.write_int('antenna', [antenna_index], 0, fft_bins=fft_bins, blindwrite=blindwrite)
            # cycle through frequencies (cannot have frequencies without antenna component)
            for index, fft_bin in enumerate(fft_bins):
                # print 'bf_read_int: setting up frequency'
                # set up frequency register
                self.write_int('frequency', [self.frequency2frequency_reg_index(fft_bins=[fft_bin])][0], 0,
                               fft_bins=[fft_bin], blindwrite=blindwrite)
                values.extend(self.read_int('value_out', offset=0, fft_bins=[fft_bin]))
            # if no frequency component, read
            if len(fft_bins) == 0:
                # read
                # print 'bf_read_int: reading for no frequencies'
                values = self.read_int('value_out', offset=0, fft_bins=fft_bins)
        if len(antenna_indices) == 0:
            # read
            # print 'bf_read_int: reading for no antennas'
            values = self.read_int('value_out', offset=0, fft_bins=fft_bins)
        return values

    def bf_write_int(self, destination, data, offset=0, beams=all, antennas=None, frequencies=None, fft_bins=[],
                     blindwrite=True):
        """write to various destinations in the bf block for a particular beam"""
        if destination == 'calibrate':
            if antennas == None:
                raise fbfException(1, 'Need to specify an antenna when writing to calibrate block',
                                   'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                                   self.syslogger)
            if frequencies == None and len(fft_bins) == 0:
                raise fbfException(1, 'Need to specify a frequency or fft bin when writing to calibrate block',
                                   'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                                   self.syslogger)
        elif destination == 'filter':
            if antennas != None:
                raise fbfException(1, 'Can''t specify antenna for filter block',
                                   'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                                   self.syslogger)
        else:
            raise fbfException(1, 'Invalid destination: %s' % destination,
                               'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                               self.syslogger)
        # convert frequencies to list of fft_bins
        if len(fft_bins) == 0:
            fft_bins = self.frequency2fft_bin(frequencies)
        # assuming people don't write to the same frequency twice
        if len(fft_bins) == self.get_param('n_chans'):
            all_freqs = True
        else:
            all_freqs = False
        # trying to write multiple data but don't have enough frequencies
        if len(data) > 1 and len(fft_bins) != len(data):
            raise fbfException(1, 'data and frequency vector lengths incompatible',
                               'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                               self.syslogger)
        # disable writes
        # print 'bf_write_int: disabling everything'
        self.write_int('control', [0x0], 0, fft_bins=fft_bins, blindwrite=blindwrite)
        if len(data) == 1:
            if self.config.simulate:
                print 'bf_write_int: setting up data for single data item'
            # set up the value to be written
            self.write_int('value_in', data, offset, fft_bins=fft_bins, blindwrite=blindwrite)
        # look up control value required to write when triggering write
        control = self.bf_control_lookup(destination, write=True, read=True)
        beams = self.beams2beams(beams)
        # cycle through beams to be written to
        for beam in beams:
            # expand, check and convert to input indices
            antennas = self.ants2ants(beam, antennas)
            antenna_indices = self.antenna2antenna_indices(beam=beam, ant_strs=antennas)
            location = self.beam2location(beams=beam)[0]
            if self.config.simulate:
                print 'bf_write_int: setting up location'
            # set up target stream (location of beam in set )
            self.write_int('stream', [location], 0, fft_bins=fft_bins, blindwrite=blindwrite)
            # go through antennas (normally just one but may be all or None)
            for antenna_index in antenna_indices:
                # if no frequency component (i.e all frequencies for this antenna)
                if self.config.simulate:
                    print 'bf_write_int: setting up antenna'
                # set up antenna register
                self.write_int('antenna', [antenna_index], 0, fft_bins=fft_bins, blindwrite=blindwrite)
                # if we are writing to all fft bins
                if all_freqs:
                    if self.config.simulate:
                        print 'bf_write_int: writing to'
                    bf_fft_bins = self.get_bf_fft_bins()
                    n_bfs = len(self.get_bfs()) * len(self.get_fpgas())
                    bins = range(0, n_bfs*bf_fft_bins, bf_fft_bins)
                    # list of previous bf values, guaranteed to not be the same for first item
                    pvals = [data[0]+1]*n_bfs
                    # cycle through all register indices
                    for reg_index in range(bf_fft_bins):
                        if self.config.simulate:
                            print 'bf_write_int: writing to frequencies that are a multiple of %d from offset %d' \
                                  % (bf_fft_bins, reg_index)
                        # write to all frequency registers
                        self.write_int('frequency', [reg_index], 0, fft_bins=bins, blindwrite=blindwrite)
                        # TODO maybe look for the same value and do asynchronous write?
                        for bf in range(n_bfs):
                            fft_bin = bf*bf_fft_bins+reg_index
                            value = data[fft_bin]
                            # if this is a new value for this bf, or first time
                            if pvals[bf] != value:
                                # now write value
                                self.write_int('value_in', [value], 0, fft_bins=[fft_bin], blindwrite=blindwrite)
                                pvals[bf] = value
                            else:
                                if self.config.simulate:
                                    print 'bf_write_int: skipping writing to bf %d' % bf
                        # trigger the write on first item (will happen automatically after that)
                        if reg_index == 0:
                            if self.config.simulate:
                                print 'bf_write_int: setting up control for first item'
                            self.write_int('control', [control], 0, fft_bins=bins, blindwrite=blindwrite)
                # otherwise we must go through one at a time
                else:
                    # cycle through frequencies
                    for index, fft_bin in enumerate(fft_bins):
                        if self.config.simulate:
                            print 'bf_write_int: setting up frequency'
                        # set up frequency register on bf associated with fft_bin being processed
                        self.write_int('frequency', [self.frequency2frequency_reg_index(fft_bins=[fft_bin])][0], 0,
                                       fft_bins=[fft_bin], blindwrite=blindwrite)
                        # we have a vector of data
                        if len(data) > 1:
                            # set up the value to be written
                            if self.config.simulate:
                                print 'bf_write_int: setting up one of multiple data values'
                            value_in = data[index]
                            # write if (we are writing all values and have just moved to next bf) or
                            # (value differs from previous)
                            self.write_int('value_in', [value_in], 0, fft_bins=[fft_bin], blindwrite=blindwrite)
                        # trigger the write
                        # set up the value to be written
                        if self.config.simulate:
                            print 'bf_write_int: triggering antenna, frequencies'
                        self.write_int('control', [control], 0, fft_bins=[fft_bin], blindwrite=blindwrite)
                # if no frequency component, trigger
                if len(fft_bins) == 0:
                    # trigger the write
                    if self.config.simulate:
                        print 'bf_write_int: triggering for no antenna but no frequencies'
                    self.write_int('control', [control], 0, fft_bins=fft_bins, blindwrite=blindwrite)
            # if no antenna component, trigger write
            if len(antenna_indices) == 0:
                # trigger the write
                if self.config.simulate:
                    print 'bf_write_int: triggering for no antennas (and no frequencies)'
                self.write_int('control', [control], 0, fft_bins=fft_bins, blindwrite=blindwrite)

    def cf_bw2fft_bins(self, centre_frequency, bandwidth):
        """returns fft bins associated with provided centre_frequency and bandwidth
        centre_frequency is assumed to be the centre of the 2^(N-1) fft bin"""
        bins = []
        n_chans = self.get_param('n_chans')
        max_bandwidth = self.get_param('bandwidth')
        fft_bin_width = self.get_fft_bin_bandwidth()
        # TODO spectral line mode systems??
        if (centre_frequency-bandwidth/2) < 0 or \
           (centre_frequency+bandwidth/2) > max_bandwidth or \
           (centre_frequency-bandwidth/2) >= (centre_frequency+bandwidth/2):
            raise fbfException(1, 'Band specified not valid for our system',
                               'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                               self.syslogger)
        # get fft bin for edge frequencies
        edge_bins = self.frequency2fft_bin(frequencies=[centre_frequency-bandwidth/2,
                                                        centre_frequency+bandwidth/2-fft_bin_width])
        bins = range(edge_bins[0], edge_bins[1]+1)
        return bins

    def cf_bw2cf_bw(self, centre_frequency, bandwidth):
        """converts specfied centre_frequency, bandwidth to values possible for our system"""
        bins = self.cf_bw2fft_bins(centre_frequency, bandwidth)
        bfs = self.frequency2bf_index(fft_bins=bins, unique=True)
        bf_bandwidth = self.get_bf_bandwidth()
        fft_bin_bandwidth = self.get_fft_bin_bandwidth()
        # calculate start frequency accounting for frequency specified in centre of bin
        start_frequency = min(bfs)*bf_bandwidth
        beam_centre_frequency = start_frequency+bf_bandwidth*(float(len(bfs))/2)
        beam_bandwidth = len(bfs) * bf_bandwidth
        return beam_centre_frequency, beam_bandwidth

    def get_enabled_fft_bins(self, beam):
        """Returns fft bins representing band that is enabled for beam"""
        bins = []
        cf = self.get_beam_param(beam, 'centre_frequency')
        bw = self.get_beam_param(beam, 'bandwidth')
        bins = self.cf_bw2fft_bins(cf, bw)
        return bins

    def get_disabled_fft_bins(self, beam):
        """Returns fft bins representing band that is disabled for beam"""
        all_bins = self.frequency2fft_bin(frequencies=all)
        enabled_bins = self.get_enabled_fft_bins(beam)
        for fft_bin in enabled_bins:
            all_bins.remove(fft_bin)
        return all_bins

# -----------------------------------
#  Interface for standard operation
# -----------------------------------

    def initialise(self, set_cal=True, config_output=True, send_spead=True):
        """Initialises the system and checks for errors."""
        # disable all beams that are transmitting
        beams = self.beams2beams(all)
        for beam in beams:
            if self.tx_status_get(beam):
                self.tx_stop(beam)
                self.syslogger.info('Stopped beamformer %s' % beam)
        # configure spead_meta data transmitter and spead data destination,
        # don't issue related spead meta-data as will do in spead_issue_all
        if config_output:
            self.config_udp_output(all, issue_spead=False)
            self.config_meta_output(all, issue_spead=False)
        else:
            self.syslogger.info('Skipped output configuration of beamformer.')
        if set_cal:
            self.cal_set_all(all, spead_issue=False)
        else:
            self.syslogger.info('Skipped calibration config of beamformer.')
        # if we set up calibration weights, then config has these already so don't
        # read from fpga
        if set_cal:
            from_fpga = False
        else:
            from_fpga = True
        if send_spead:
            self.spead_issue_all(beams=all, from_fpga=from_fpga)
        else:
            self.syslogger.info('Skipped issue of spead meta data.')
        self.syslogger.info("Beamformer initialisation complete.")

    def tx_start(self, beams=all):
        """Start outputting SPEAD products. Only works for systems with 10GbE output atm."""
        if self.get_param('out_type') == '10gbe':
            # NOTE that the order of the following operations is significant
            # output from bfs will be enabled if any component frequencies are required
            # convert to actual beam names
            beams = self.beams2beams(beams)
            beam_indices = self.beam2index(beams)
            for index, beam in enumerate(beams):
                beam_index = beam_indices[index]
                # get frequency_indices associated with disabled parts of beam
                disabled_fft_bins = self.get_disabled_fft_bins(beam)
                if len(disabled_fft_bins) > 0:
                    if self.config.simulate == True:
                        print 'disabling excluded bfs'
                    # disable bfs not required via the filter block in the beamformer
                    self.bf_write_int(destination='filter', data=[0x0], offset=0x0, beams=beam,
                                      fft_bins=disabled_fft_bins)
                    if self.config.simulate == True:
                        print 'configuring excluded bfs'
                    # configure disabled beamformers to output to HEAP 0 HEAP size of 0, offset 0
                    bf_config = ((0 << 16) & 0x7fff0000 | (0 << 8) & 0x0000ff00 | 0 & 0x000000ff)
                    self.write_int('cfg%i' % beam_index, [bf_config], 0, fft_bins=disabled_fft_bins)
                # get frequency_indices associated with enabled parts of beams
                enabled_fft_bins = self.get_enabled_fft_bins(beam)
                # reset speadify blocks associated with fft bins required
                fpga_bf_e = self.frequency2fpga_bf(fft_bins=enabled_fft_bins, unique=True)
                bf_config = []
                for offset in range(len(fpga_bf_e)):
                    bf_config.append((1 << 31))
                if self.config.simulate == True:
                    print 'resetting included speadify blocks'
                self.write_int('cfg%i' % beam_index, bf_config, 0, fft_bins=enabled_fft_bins)
                # generate vector of values that will match the number of bfs in the list
                bf_config = []
                for offset in range(len(fpga_bf_e)):
                    bf_config.append((beam_index << 16) & 0x7fff0000 | (len(fpga_bf_e) << 8) & 0x0000ff00 |
                                     offset & 0x000000ff)
                if self.config.simulate == True: print 'configuring included bfs'
                self.write_int('cfg%i' % beam_index, bf_config, 0, fft_bins=enabled_fft_bins)
                if self.config.simulate == True:
                    print 'enabling included bfs'
                # lastly enable those parts
                self.bf_write_int(destination='filter', data=[0x1], offset=0x0, beams=beam, fft_bins=enabled_fft_bins)
                self.syslogger.info('Output for %s started' % beam)
        else:
            raise fbfException(1, 'Sorry, your output type is not supported. Could not enable output.',
                               'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                               self.syslogger)

    def tx_stop(self, beams=all, spead_stop=True):
        """Stops outputting SPEAD data over 10GbE links for specified beams.
        Sends SPEAD packets indicating end of stream if required"""
        beams = self.beams2beams(beams)
        if self.get_param('out_type') == '10gbe':
            for beam in beams:
                # disable all bf outputs
                self.bf_write_int(destination='filter', data=[0x0], offset=0x0, beams=beams)
                self.syslogger.info("Beamformer output paused for beam %s" % beam)
                if spead_stop:
                    if self.config.simulate == True:
                        print 'tx_stop: dummy ending SPEAD stream for beam %s' % beam
                    else:
                        spead_tx = self.get_spead_tx(beam)
                        spead_tx.send_halt()
                        self.syslogger.info("Sent SPEAD end-of-stream notification for beam %s" % beam)
                else:
                    self.syslogger.info("Did not send SPEAD end-of-stream notification for beam %s" % beam)
        else:
            raise fbfException(1, 'Sorry, your output type is not supported. Cannot disable output for beam %s.'
                               % beams, 'function %s, line no %s\n'
                               % (__name__, inspect.currentframe().f_lineno), self.syslogger)

    def tx_status_get(self, beam):
        """Returns boolean true/false if the beamformer is currently outputting data.
        Currently only works on systems with 10GbE output."""
        # if simulating, no beam is enabled
        if self.config.simulate:
            return False
        if self.get_param('out_type') != '10gbe':
                raise fbfException(1, 'This function only works for systems with 10GbE output!',
                                   'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                                   self.syslogger)
        rv = True
        # check 10Ge cores are not in reset
        stat = self.c.xeng_ctrl_get_all()
        for xn in stat:
            if xn['gbe_out_rst'] != False:
                rv = False
        self.syslogger.info('10Ge output is currently %s' % ('enabled' if rv else 'disabled'))
        # read output status of beams
        mask = self.bf_read_int(beam=beam, destination='filter')
        # look to see if any portion in enabled
        if mask.count(1) != 0:
            rv = rv
        else:
            rv = False
        return rv

    def config_meta_output(self, beams=all, dest_ip_str=None, dest_port=None, issue_spead=True):
        """Configures the destination IP and port for SPEAD meta-data outputs. dest_port and
        dest_ip are optional parameters to override the config file defaults."""
        beams = self.beams2beams(beams)
        for beam in beams:
            if dest_ip_str == None:
                rx_meta_ip_str = self.get_beam_param(beam, 'rx_meta_ip_str')
            else:
                rx_meta_ip_str = dest_ip_str
                self.set_beam_param(beam, 'rx_meta_ip_str', dest_ip_str)
                self.set_beam_param(beam, 'rx_meta_ip', struct.unpack('>L', socket.inet_aton(dest_ip_str))[0])

            if dest_port == None:
                rx_meta_port = self.get_beam_param(beam, 'rx_meta_port')
            else:
                rx_meta_port = dest_port
                self.set_beam_param(beam, 'rx_meta_port', dest_port)

            self.spead_tx['bf_spead_tx_beam%i' % self.beam2index(beam)[0]] = \
                spead.Transmitter(spead.TransportUDPtx(rx_meta_ip_str, rx_meta_port))
            self.syslogger.info("Destination for SPEAD meta data transmitter for beam %s changed. "
                                "New destination IP = %s, port = %d" % (beam, rx_meta_ip_str, rx_meta_port))
            # reissue all SPEAD meta-data to new receiver
            if issue_spead:
                self.spead_issue_all(beam)

    def config_udp_output(self, beams=all, dest_ip_str=None, dest_port=None, issue_spead=True):
        """Configures the destination IP and port for B engine data outputs. dest_port and dest_ip
        are optional parameters to override the config file defaults."""
        beams = self.beams2beams(beams)
        for beam in beams:
            if dest_ip_str == None:
                rx_udp_ip_str = self.get_beam_param(beam, 'rx_udp_ip_str')
            else:
                rx_udp_ip_str = dest_ip_str
                self.set_beam_param(beam, 'rx_udp_ip_str', dest_ip_str)
                self.set_beam_param(beam, 'rx_udp_ip', struct.unpack('>L', socket.inet_aton(dest_ip_str))[0])
            if dest_port == None:
                rx_udp_port = self.get_beam_param(beam, 'rx_udp_port')
            else:
                rx_udp_port = dest_port
                self.set_beam_param(beam, 'rx_udp_port', dest_port)
            beam_offset = self.get_beam_param(beam, 'location')
            dest_ip = struct.unpack('>L', socket.inet_aton(rx_udp_ip_str))[0]
            # restart if currently transmitting
            restart = self.tx_status_get(beam)
            if restart:
                self.tx_stop(beam)
            self.write_int('dest', data=[dest_ip], offset=(beam_offset*2))
            self.write_int('dest', data=[rx_udp_port], offset=(beam_offset*2+1))
            # each beam output from each beamformer group can be configured differently
            self.syslogger.info("Beam %s configured to output to %s:%i." % (beam, rx_udp_ip_str, rx_udp_port))
            if issue_spead:
                self.spead_destination_meta_issue(beam)
            if restart:
                self.tx_start(beam)

    def set_passband(self, beams=all, centre_frequency=None, bandwidth=None, spead_issue=True):
        """sets the centre frequency and/or bandwidth for the specified beams"""
        beams = self.beams2beams(beams)
        max_bandwidth = self.get_param('bandwidth')
        for beam in beams:
            # parameter checking
            if centre_frequency == None:
                cf = self.get_beam_param(beam, 'centre_frequency')
            else:
                cf = centre_frequency
            if bandwidth == None:
                b = self.get_beam_param(beam, 'bandwidth')
            else:
                b = bandwidth
            cf_actual, b_actual = self.cf_bw2cf_bw(cf, b)
            if centre_frequency != None:
                self.set_beam_param(beam, 'centre_frequency', cf_actual)
                self.syslogger.info('Centre frequency for beam %s set to %i Hz' % (beam, cf_actual))
            if bandwidth != None:
                self.set_beam_param(beam, 'bandwidth', b_actual)
                self.syslogger.info('Bandwidth for beam %s set to %i Hz' % (beam, b_actual))
            if centre_frequency != None or bandwidth != None:
                # restart if currently transmitting
                restart = self.tx_status_get(beam)
                if restart:
                    self.tx_stop(beam)
                # issue related spead meta data
                if spead_issue:
                    self.spead_passband_meta_issue(beam)
                if restart:
                    self.syslogger.info('Restarting beam %s with new passband parameters' % beam)
                    self.tx_start(beam)

    def get_passband(self, beam):
        """gets the centre frequency and bandwidth for the specified beam"""
        # parameter checking
        cf = self.get_beam_param(beam, 'centre_frequency')
        b = self.get_beam_param(beam, 'bandwidth')
        cf_actual, b_actual = self.cf_bw2cf_bw(cf, b)
        return cf_actual, b_actual

    def get_n_chans(self, beam):
        """gets the number of active channels for the specified beam"""
        fft_bin_bandwidth = self.get_fft_bin_bandwidth()
        cf, bw = self.get_passband(beam)
        n_chans = bw/fft_bin_bandwidth
        return n_chans

#   CALIBRATION

    def cal_set_all(self, beams, init_poly=[], init_coeffs=[], spead_issue=True):
        """Initialise all antennas for all specified beams' calibration factors to given polynomial.
        If no polynomial or coefficients are given, use defaults from config file."""
        beams = self.beams2beams(beams)
        # go through all beams specified
        for beam in beams:
            # get all antenna input strings
            ant_strs = self.ants2ants(beam, all)
            # go through all antennas for beams
            for ant_str in ant_strs:
                self.cal_spectrum_set(beam=beam, ant_str=ant_str, init_coeffs=init_coeffs,
                                      init_poly=init_poly, spead_issue=False)
            # issue spead packet only once all antennas are done, and don't read the values back (we have just set them)
            if spead_issue:
                self.spead_cal_meta_issue(beam, from_fpga=False)

    def cal_default_get(self, beam, ant_str):
        """Fetches the default calibration configuration from the config file and returns
        a list of the coefficients for a given beam and antenna."""
        n_coeffs = self.get_param('n_chans')
        input_n = self.map_ant_to_input(beam=beam, ant_strs=[ant_str])[0]
        cal_default = self.get_beam_param(beam,'cal_default_input%i' % input_n)
        if cal_default == 'coeffs':
            calibration = self.get_beam_param(beam, 'cal_coeffs_input%i' % input_n)
        elif cal_default == 'poly':
            poly = self.get_beam_param(beam, 'cal_poly_input%i' % input_n)
            calibration = numpy.polyval(poly, range(n_coeffs))
            if self.get_param('bf_cal_type') == 'complex':
                calibration = [cal+0*1j for cal in calibration]
        else:
            raise fbfException(1, 'Your default beamformer calibration type, %s, is not understood.' % cal_default,
                               'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                               self.syslogger)
        if len(calibration) != n_coeffs:
            raise fbfException(1, 'Something\'s wrong. I have %i calibration coefficients when I should have %i.'
                               % (len(calibration), n_coeffs),
                               'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                               self.syslogger)
        return calibration

    def cal_default_set(self, beam, ant_str, init_coeffs=[], init_poly=[]):
        """store current calibration settings in configuration"""
        n_coeffs = self.get_param('n_chans')
        input_n = self.map_ant_to_input(beam=beam, ant_strs=[ant_str])[0]
        if len(init_coeffs) == n_coeffs:
            self.set_beam_param(beam, 'cal_coeffs_input%i' % input_n, [init_coeffs])
            self.set_beam_param(beam, 'cal_default_input%i' % input_n, 'coeffs')
        elif len(init_poly) > 0:
            self.set_beam_param(beam, 'cal_poly_input%i' % input_n, [init_poly])
            self.set_beam_param(beam, 'cal_default_input%i' % input_n, 'poly')
        else:
            raise fbfException(1, 'calibration settings are not sensical',
                               'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                               self.syslogger)

    def cal_fpga2floats(self, data):
        """Converts vector of values in format as from FPGA to float vector"""
        values = []
        n_bits = self.get_param('bf_cal_n_bits')
        bin_pt = self.get_param('bf_cal_bin_pt')
        for datum in data:
            val_real = (numpy.int16((datum & 0xFFFF0000) >> 16))
            val_imag = (numpy.int16(datum & 0x0000FFFF))
            datum_real = numpy.float(val_real)/(2**bin_pt)
            datum_imag = numpy.float(val_imag)/(2**bin_pt)
            values.append(complex(datum_real, datum_imag))
        return values

    def cal_spectrum_get(self, beam, ant_str, from_fpga=True):
        """Retrieves the calibration settings currently programmed in all bengines
        for the given beam and antenna. Returns an array of length n_chans."""
        if from_fpga:
            # read them directly from fpga
            fpga_values = self.bf_read_int(beam=beam, destination='calibrate', offset=0, antennas=[ant_str],
                                           frequencies=all)
            # float_values are not assigned here
        else:
            base_values = self.cal_default_get(beam, ant_str)
            # calculate values that would be written to fpga
            fpga_values = self.cal_floats2fpga(base_values)
            float_values = self.cal_fpga2floats(fpga_values)
        return float_values

    def cal_floats2fpga(self, data):
        """Convert floating point values to vector for writing to FPGA"""
        values = []
        bf_cal_type = self.get_param('bf_cal_type')
        if bf_cal_type == 'scalar':
            data = numpy.real(data)
        elif bf_cal_type == 'complex':
            data = numpy.array(data, dtype=numpy.complex128)
        else:
            raise fbfException(1, 'Sorry, your beamformer calibration type is not supported. Expecting scalar '
                                  'or complex.', 'function %s, line no %s\n'
                               % (__name__, inspect.currentframe().f_lineno), self.syslogger)
        n_bits = self.get_param('bf_cal_n_bits')
        bin_pt = self.get_param('bf_cal_bin_pt')
        whole_bits = n_bits-bin_pt
        top = 2**(whole_bits-1)-1
        bottom = -2**(whole_bits-1)
        if (max(numpy.real(data)) > top or min(numpy.real(data)) < bottom):
            self.syslogger.info('real calibration values out of range, will saturate')
        if (max(numpy.imag(data)) > top or min(numpy.imag(data)) < bottom):
            self.syslogger.info('imaginary calibration values out of range, will saturate')
        # convert data
        for datum in data:
            datum_real = numpy.real(datum)
            datum_imag = numpy.imag(datum)
            # shift up for binary point
            val_real = numpy.int32(datum_real * (2**bin_pt))
            val_imag = numpy.int32(datum_imag * (2**bin_pt))
            # pack real and imaginary values into 32 bit value
            values.append((val_real << 16) | (val_imag & 0x0000FFFF))
        return values

    def cal_spectrum_set(self, beam, ant_str, init_coeffs=[], init_poly=[], spead_issue=True):
        """Set given beam and antenna calibration settings to given co-efficients."""
        if self.config.simulate:
            print 'setting spectrum for beam %s antenna %s' % (beam, ant_str)
        n_coeffs = self.get_param('n_chans')
        if init_coeffs == [] and init_poly == []:
            coeffs = self.cal_default_get(beam=beam, ant_str=ant_str)
        elif len(init_coeffs) == n_coeffs:
            coeffs = init_coeffs
            self.cal_default_set(beam, ant_str, init_coeffs=init_coeffs)
        elif len(init_coeffs) > 0:
            raise fbfException(1, 'You specified %i coefficients, but there are %i cal coefficients '
                                  'required for this design.' % (len(init_coeffs), n_coeffs),
                               'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                               self.syslogger)
        else:
            coeffs = numpy.polyval(init_poly, range(n_coeffs))
            self.cal_default_set(beam, ant_str, init_poly=init_poly)
            fpga_values = self.cal_floats2fpga(data=coeffs)
            # write final vector to calibrate block
            self.bf_write_int('calibrate', fpga_values, offset=0, beams=[beam], antennas=[ant_str], frequencies=all)
        if spead_issue:
            self.spead_cal_meta_issue(beam, from_fpga=False)

# -----------
#   SPEAD
# -----------

    def spead_initialise(self):
        """creates spead transmitters that will be used by the beams in our system"""
        self.spead_tx = dict()
        # create a spead transmitter for every beam and store in config
        for beam in self.beams2beams(all):
            ip_str = self.get_beam_param(beam, 'rx_meta_ip_str')
            port = self.get_beam_param(beam, 'rx_meta_port')
            self.spead_tx['bf_spead_tx_beam%i' % self.beam2index(beam)[0]] = \
                spead.Transmitter(spead.TransportUDPtx(ip_str, port))
            self.syslogger.info("Created spead transmitter for beam %s. Destination IP = %s, port = %d"
                                % (beam, ip_str, port))

    def get_spead_tx(self, beam):
        beam = self.beams2beams(beam)
        beam_index = self.beam2index(beam)[0]
        try:
            spead_tx = self.spead_tx['bf_spead_tx_beam%i' % beam_index]
        except:
            raise fbfException(1, 'Error locating SPEAD transmitter for beam %s' % beam,
                               'function %s, line no %s\n' % (__name__, inspect.currentframe().f_lineno),
                               self.syslogger)
        return spead_tx

    def send_spead_heap(self, beam, ig):
        """Sends spead item group via transmitter for beam specified"""

        beam = self.beams2beams(beam)
        spead_tx = self.get_spead_tx(beam)
        if self.config.simulate:
            print 'dummy sending spead heap'
        else:
            spead_tx.send_heap(ig.get_heap())

    def spead_labelling_issue(self, beams=all):
        """Issues the SPEAD metadata packets describing the labelling/location/connections
        of the system's analogue inputs."""
        beams = self.beams2beams(beams)
        spead_ig = spead.ItemGroup()
        spead_ig.add_item(name="input_labelling", id=0x100E,
            description="The physical location of each antenna connection.",
            init_val=numpy.array([(ant_str, input_n, lru, feng_input) for
                                  (ant_str, input_n, lru, feng_input) in self.c.adc_lru_mapping_get()]))
        for beam in beams:
            if self.config.simulate:
                print 'Issuing labelling meta data for beam %s' % beam
            self.send_spead_heap(beam, spead_ig)
            self.syslogger.info("Issued SPEAD metadata describing baseline labelling and "
                                    "input mapping for beam %s" % beam)

    def spead_static_meta_issue(self, beams=all):
        """ Issues the SPEAD metadata packets containing the payload and options descriptors and unpack sequences."""
        beams = self.beams2beams(beams)
        # spead stuff that does not care about beam
        spead_ig = spead.ItemGroup()
        spead_ig.add_item(name="adc_clk", id=0x1007, description="Clock rate of ADC (samples per second).", shape=[],
                          fmt=spead.mkfmt(('u', 64)), init_val=self.get_param('adc_clk'))
        spead_ig.add_item(name="n_ants", id=0x100A, description="The total number of dual-pol antennas in the system.",
                          shape=[], fmt=spead.mkfmt(('u', spead.ADDRSIZE)), init_val=self.get_param('n_ants'))
        spead_ig.add_item(name="n_bengs", id=0x100F, description="The total number of B engines in the system.",
                          shape=[], fmt=spead.mkfmt(('u', spead.ADDRSIZE)),
                          init_val=self.get_param('bf_be_per_fpga')*len(self.get_fpgas()))
        # 1015/1016 are taken (see time_metadata_issue below)
        spead_ig.add_item(name="xeng_acc_len", id=0x101F,
                          description="Number of spectra accumulated inside X engine. Determines minimum integration "
                          "time and user-configurable integration time stepsize. X-engine correlator internals.",
                          shape=[], fmt=spead.mkfmt(('u', spead.ADDRSIZE)), init_val=self.get_param('xeng_acc_len'))
        spead_ig.add_item(name="requant_bits", id=0x1020,
                          description="Number of bits after requantisation in the F engines (post FFT and any "
                                      "phasing stages).", shape=[], fmt=spead.mkfmt(('u', spead.ADDRSIZE)),
                          init_val=self.get_param('feng_bits'))
        spead_ig.add_item(name="feng_pkt_len", id=0x1021,
                          description="Payload size of 10GbE packet exchange between F and X engines in 64 bit words. "
                                      "Usually equal to the number of spectra accumulated inside X engine. F-engine "
                                      "correlator internals.", shape=[], fmt=spead.mkfmt(('u', spead.ADDRSIZE)),
                                      init_val=self.get_param('10gbe_pkt_len'))
        spead_ig.add_item(name="feng_udp_port", id=0x1023, description="Destination UDP port for B engine data exchange.",
                          shape=[], fmt=spead.mkfmt(('u', spead.ADDRSIZE)), init_val=self.get_param('10gbe_port'))
        spead_ig.add_item(name="feng_start_ip", id=0x1025, description="F engine starting IP address.", shape=[],
                          fmt=spead.mkfmt(('u', spead.ADDRSIZE)), init_val=self.get_param('10gbe_ip'))
        # TODO ADD VERSION INFO!
        spead_ig.add_item(name="b_per_fpga", id=0x1047, description="The number of b-engines per fpga.", shape=[],
                          fmt=spead.mkfmt(('u', spead.ADDRSIZE)), init_val=self.get_param('bf_be_per_fpga'))
        spead_ig.add_item(name="ddc_mix_freq", id=0x1043, description="Digital downconverter mixing freqency as a "
                                                                      "fraction of the ADC sampling frequency. eg: "
                                                                      "0.25. Set to zero if no DDC is present.",
                          shape=[], fmt=spead.mkfmt(('f', 64)), init_val=self.get_param('ddc_mix_freq'))
        spead_ig.add_item(name="adc_bits", id=0x1045, description="ADC quantisation (bits).", shape=[],
                          fmt=spead.mkfmt(('u', spead.ADDRSIZE)), init_val=self.get_param('adc_bits'))
        spead_ig.add_item(name="beng_out_bits_per_sample", id=0x1050, description="The number of bits per value in "
                                                                                  "the beng output. Note that this is "
                                                                                  "for a single value, not the combined"
                                                                                  " complex value size.", shape=[],
                          fmt=spead.mkfmt(('u', spead.ADDRSIZE)), init_val=self.get_param('bf_bits_out'))
        spead_ig.add_item(name="fft_shift", id=0x101E, description="The FFT bitshift pattern. F-engine correlator "
                                                                   "internals.", shape=[],
                          fmt=spead.mkfmt(('u', spead.ADDRSIZE)), init_val=self.config['fft_shift'])
        # timestamp
        spead_ig.add_item(name='timestamp', id=0x1600, description='Timestamp of start of this block of data. '
                                                                   'uint counting multiples of ADC samples since last '
                                                                   'sync (sync_time, id=0x1027). Divide this number by '
                                                                   'timestamp_scale (id=0x1046) to get back to seconds '
                                                                   'since last sync when this block of data started.',
                          shape=[], fmt=spead.mkfmt(('u', spead.ADDRSIZE)), init_val=0)
        for beam in beams:
            if self.config.simulate:
                print 'Issuing static meta data for beam %s' % beam
            self.send_spead_heap(beam, spead_ig)
            self.syslogger.info("Issued static SPEAD metadata for beam %s" % beam)

    def spead_destination_meta_issue(self, beams=all):
        """Issues a SPEAD packet to notify the receiver of changes to destination"""
        beams = self.beams2beams(beams)
        for beam in beams:
            spead_ig = spead.ItemGroup()
            spead_ig.add_item(name="rx_udp_port", id=0x1022, description="Destination UDP port for B engine output.",
                              shape=[], fmt=spead.mkfmt(('u', spead.ADDRSIZE)),
                              init_val=self.get_beam_param(beam, 'rx_udp_port'))
            spead_ig.add_item(name="rx_udp_ip_str", id=0x1024, description="Destination IP address for B engine "
                                                                           "output UDP packets.", shape=[-1],
                              fmt=spead.STR_FMT, init_val=self.get_beam_param(beam, 'rx_udp_ip_str'))
            if self.config.simulate:
                print 'Issuing destination meta data for beam %s' % beam
                self.send_spead_heap(beam, spead_ig)
                self.syslogger.info("Issued destination SPEAD metadata for beam %s" % beam)

    def spead_passband_meta_issue(self, beams=all):
        """Issues a SPEAD packet to notify the receiver of changes to passband parameters"""
        beams = self.beams2beams(beams)
        for beam in beams:
            spead_ig = spead.ItemGroup()
            cf, bw = self.get_passband(beam)
            spead_ig.add_item(name="center_freq", id=0x1011, description="The center frequency of the output data "
                                                                         "in Hz, 64-bit IEEE floating-point number.",
                              shape=[], fmt=spead.mkfmt(('f', 64)), init_val=cf)
            spead_ig.add_item(name="bandwidth", id=0x1013, description="The analogue bandwidth of the digitally "
                                                                       "processed signal in Hz.", shape=[],
                              fmt=spead.mkfmt(('f',64)), init_val=bw)
            spead_ig.add_item(name="n_chans", id=0x1009, description="The total number of frequency channels present "
                                                                     "in the output data.", shape=[],
                              fmt=spead.mkfmt(('u',spead.ADDRSIZE)), init_val=self.get_n_chans(beam))
            # data item
            beam_index = self.beam2index(beam)[0]
            # id is 0xB + 12 least sig bits id of each beam
            beam_data_id = 0xB000 | (beam_index & 0x00000FFF)
            spead_ig.add_item(name=beam, id=beam_data_id, description="Raw data for bengines in the system. "
                                                                      "Frequencies are assembled from lowest frequency "
                                                                      "to highest frequency. Frequencies come in blocks"
                                                                      " of values in time order where the number of "
                                                                      "samples in a block is given by xeng_acc_len "
                                                                      "(id 0x101F). Each value is a complex number -- "
                                                                      "two (real and imaginary) signed integers.",
                              ndarray=numpy.ndarray(shape=(self.get_n_chans(beam), self.get_param('xeng_acc_len'), 2),
                                                    dtype=numpy.int8))
            if self.config.simulate:
                print 'Issuing passband meta data for beam %s' % beam
                self.send_spead_heap(beam, spead_ig)
                self.syslogger.info("Issued passband SPEAD metadata for beam %s" % beam)

    def spead_time_meta_issue(self, beams=all):
        """Issues a SPEAD packet to notify the receiver that we've resync'd the system, acc len has changed etc."""
        beams = self.beams2beams(beams)
        spead_ig = spead.ItemGroup()
        # sync time
        if self.config.simulate:
            val = 0
        else:
            val = self.get_param('sync_time')
        spead_ig.add_item(name='sync_time', id=0x1027, description="Time at which the system was last synchronised "
                                                                   "(armed and triggered by a 1PPS) in seconds since"
                                                                   " the Unix Epoch.", shape=[],
                          fmt=spead.mkfmt(('u', spead.ADDRSIZE)), init_val=val)
        # scale factor for timestamp
        spead_ig.add_item(name="scale_factor_timestamp", id=0x1046, description="Timestamp scaling factor. Divide the "
                                                                                "SPEAD data packet timestamp by this "
                                                                                "number to get back to seconds since"
                                                                                " last sync.", shape=[],
                          fmt=spead.mkfmt(('f', 64)), init_val=self.get_param('spead_timestamp_scale_factor'))
        for beam in beams:
            ig = spead_ig
            if self.config.simulate:
                    print 'Issuing time meta data for beam %s' % beam
            self.send_spead_heap(beam, ig)
            self.syslogger.info("Issued SPEAD timing metadata for beam %s" % beam)

    def spead_eq_meta_issue(self, beams=all):
        """Issues a SPEAD heap for the RF gain and EQ settings settings."""
        beams = self.beams2beams(beams)
        spead_ig = spead.ItemGroup()
        # RF
        if self.get_param('adc_type') == 'katadc':
            for input_n, ant_str in enumerate(self.c.config._get_ant_mapping_list()):
                spead_ig.add_item(name="rf_gain_%i" % input_n, id=0x1200+input_n, description="The analogue RF gain "
                                                                                              "applied at the ADC for "
                                                                                              "input %i (ant %s) in dB."
                                                                                              % (input_n, ant_str),
                                  shape=[], fmt=spead.mkfmt(('f', 64)), init_val=self.get_param('rf_gain_%i'
                                                                                                % input_n))
        # equaliser settings
        for in_n, ant_str in enumerate(self.c.config._get_ant_mapping_list()):
            if self.config.simulate:
                vals = [[numpy.real(coeff), numpy.imag(coeff)] for coeff in self.c.eq_default_get(ant_str)]
            else:
                vals = [[numpy.real(coeff),numpy.imag(coeff)] for coeff in self.c.eq_spectrum_get(ant_str)]
            spead_ig.add_item(name="eq_coef_%s" % ant_str, id=0x1400+in_n, description="The unitless per-channel "
                                                                                       "digital scaling factors "
                                                                                       "implemented prior to "
                                                                                       "requantisation, post-FFT, for "
                                                                                       "input %s. Complex number real,"
                                                                                       "imag 32 bit integers."
                                                                                       % ant_str,
                              shape=[self.get_param('n_chans'), 2], fmt=spead.mkfmt(('u', 32)), init_val=vals)
        for beam in beams:
            if self.config.simulate:
                print 'Issuing equalisation and rf meta data for beam %s' % beam
            self.send_spead_heap(beam, spead_ig)
            self.syslogger.info("Issued SPEAD EQ and RF metadata for beam %s" % beam)

    def spead_cal_meta_issue(self, beams=all, from_fpga=True):
        """Issues a SPEAD heap for the RF gain, EQ settings and calibration settings."""
        beams = self.beams2beams(beams)
        spead_ig = spead.ItemGroup()
        # override if simulating
        if self.config.simulate:
            from_fpga = False
        for beam in beams:
            ig = spead_ig
            # calibration settings
            for in_n, ant_str in enumerate(self.ants2ants(beam, all)):
                vals = [[numpy.real(coeff), numpy.imag(coeff)] for coeff in
                        self.cal_spectrum_get(beam, ant_str, from_fpga)]
                ig.add_item(name="beamweight_input%s" % ant_str, id=0x2000+in_n, description="The unitless per-channel "
                                                                                             "digital scaling factors "
                                                                                             "implemented prior to "
                                                                                             "combining antenna signals"
                                                                                             " during beamforming for "
                                                                                             "input %s. Complex number "
                                                                                             "real,imag 64 bit floats."
                                                                                             % ant_str,
                            shape=[self.get_param('n_chans'), 2], fmt=spead.mkfmt(('f', 64)), init_val=vals)
            if self.config.simulate:
                print 'Issuing calibration meta data for beam %s' % beam
                self.send_spead_heap(beam, ig)
                self.syslogger.info("Issued SPEAD EQ metadata for beam %s" % beam)

    def spead_issue_all(self, beams=all, from_fpga=True):
        """Issues all SPEAD metadata."""
        self.spead_static_meta_issue(beams)
        self.spead_passband_meta_issue(beams)
        self.spead_destination_meta_issue(beams)
        self.spead_time_meta_issue(beams)
        self.spead_eq_meta_issue(beams)
        self.spead_cal_meta_issue(beams=beams, from_fpga=from_fpga)
        self.spead_labelling_issue(beams)

