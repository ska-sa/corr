#!/usr/bin/env python
""" This script provides a very basic KATCP interface to the correlator. It does not include any debug facilities beyond basic logging.
Author: Jason Manley
Date: 2010-11-11"""

import logging,corr,sys,Queue,katcp,time
from optparse import OptionParser
from katcp.kattypes import request, return_reply, Float, Int, Str, Bool
import struct, re, string

logging.basicConfig(level=logging.WARN,
                    stream=sys.stderr,
                    format="%(asctime)s - %(name)s - %(filename)s:%(lineno)s - %(levelname)s - %(message)s")

class DeviceExampleServer(katcp.DeviceServer):

    ## Interface version information.
    VERSION_INFO = ("Python CASPER packetised correlator server", 0, 1)

    ## Device server build / instance information.
    BUILD_INFO = ("corr", 0, 1, "rc2")

    #pylint: disable-msg=R0904
    def setup_sensors(self):
        pass

    def __init__(self, *args, **kwargs):
        super(DeviceExampleServer, self).__init__(*args, **kwargs)
        self.c = None # correlator object
        self.b = None # beamformer object

    @request(Int(default=-1))
    @return_reply(Int(), Int(), Int())
    def request_nb_set_cf(self, sock, freq):
        """Sets the center frequency for narrowband."""
        if self.c is None:
            return ("fail","... you haven't connected yet!")
        try:
            rva, rvb, rvc = corr.corr_nb.channel_select(c = self.c, freq_hz = freq)
            return ("ok", rva, rvb, rvc)
        except:
            return ("fail", "Something broke spectacularly. Check the log.")

    @request(Str(default='/etc/corr/default'), Int(default=100), include_msg=True)
    @return_reply()
    def request_connect(self, sock, orgmsg, config_file, log_len):
        """Connect to all the ROACH boards. Please specify the config file and the log length. Clears any existing log. Call this again if you make external changes to the config file to reload it."""
        self.lh = corr.log_handlers.DebugLogHandler(log_len)
        try:
            self.c = corr.corr_functions.Correlator(config_file=config_file,log_handler=self.lh,log_level=logging.INFO)
        except Exception as err_msg:
            return ("fail", err_msg)
        try:
            self.b = corr.bf_functions.fbf(host_correlator=self.c, optimisations=True)
        except:
            self.reply_inform(sock, katcp.Message.inform(orgmsg.name, "Beamformer not available"),orgmsg)
            pass
        return ("ok",)

    @request(include_msg=True)
    @return_reply(Int(min=0))
    def request_get_rcs(self, sock,orgmsg):
        """Get the revision control information for the system."""
        if self.c is None:
            return katcp.Message.reply("fail","... you haven't connected yet!")
        rcs=self.c.get_rcs()
        ret_line=[]
        for e,r in rcs.iteritems():
            for k,s in r.iteritems():
                ret_line.append('%s:%s:%s'%(e,k,s))
                self.reply_inform(sock, katcp.Message.inform(orgmsg.name,ret_line[-1]),orgmsg)
        return ("ok",len(ret_line))


    @request(Int(default=100))
    @return_reply()
    def request_initialise(self, sock, n_retries):
        """Initialise the correlator. This programs the FPGAs, configures network interfaces etc. Includes error checks. Beamformer mode will update and add relevant functionality and SPEAD metadata. Consult the log in event of errors."""
        # First initiate the correlator
        if self.c is None:
            return ("fail","... you haven't connected yet!")
        try: 
            self.c.initialise(n_retries)
        except:
            return ("fail","Correlator could not initialise. Check the log.")

        # Next, if beamformer object is instantiated, initiate the beamformer
        if self.b is not None:
            try:
              time.sleep(1) # allow little time for corr init to close
              self.b.initialise()
            except:
              return("fail","Beamformer could not initialise. Check the log.")

        return ("ok",)


    @request(include_msg=True)
    @return_reply(Int(min=0))
    def request_get_log(self, sock, orgmsg):
        """Fetch the log."""
        if self.c is None:
            return ("fail","... you haven't connected yet!")

        print "\nlog:"
        self.lh.printMessages()

        for logent in self.c.log_handler._records:
            if logent.exc_info:
                print '%s: %s Exception: '%(logent.name,logent.msg),logent.exc_info[0:-1]
                self.reply_inform(sock, katcp.Message.inform("log",'%s: %s Exception: '%(logent.name,logent.msg),logent.exc_info[0:-1]),orgmsg)        
            else:
#log error 1234567 basic "the error string"
                self.reply_inform(sock, katcp.Message.inform("log", logent.levelname.lower() if logent.levelname.lower() != 'warning' else 'warn', '%i'%(logent.created*1000), logent.name ,logent.msg),orgmsg)
                #print 'Sending this message:',logent.msg
        return ("ok", len(self.c.log_handler._records))

    @request()
    @return_reply()
    def request_clr_log(self, sock):
        """Clears the log."""
        if self.c is None:
            return ("fail","... you haven't connected yet!")
        self.c.log_handler.clear()
        return ("ok",)

    @request(Int(),Str())
    @return_reply(Str())
    def request_label_input(self, sock, input_n, ant_str):
        """Label the inputs. First argument is integer specifying the physical connection. Ordering: first input of first feng, second input of first feng, ... , first input of second feng, second input of second feng, ... , second-last input of last feng, last input of last feng."""
        if self.c is None:
            return ("fail","... you haven't connected yet!")
        if (input_n < self.c.config['n_inputs']):
            self.c.label_input(input_n,ant_str)
            # currently the correlator has no concept of the beamformer
            # when the correlator label_input has been updated and a beamformer is known, the SPEAD metadata for the beamformer should be re-issued as well
            # default is to issue to all beams
            if self.b is not None: self.b.spead_labelling_issue()
            return("ok","Input %i relabelled to %s."%(input_n,ant_str))
        else:
            #return("fail","it broke.")
            return("fail","Sorry, your input number is invalid. Valid range: 0 to %i."%(self.c.config['n_inputs']-1))


    @return_reply(Str(),Str())
    def request_bf_destination(self, sock, orgmsg):
        """Set destination for a given stream to a new IP address. The first argument should be the stream name, the second meta/data, the third the IP address in dotted-quad notation. An optional fourth parameters is the port."""
        if self.c is None:
            return ("fail","... you haven't connected yet!")
        if self.b is None:
            return ("fail","... no beamformer available!")
        if len(orgmsg.arguments) < 3: return ("fail", "... usage: <stream> <meta/data> <ip> [port]")
        stream     = orgmsg.arguments[0]
        identifier = orgmsg.arguments[1]
        ip         = orgmsg.arguments[2]

        if not stream in self.b.get_beams():
            return ("fail", "... name %s not a known beam!"%(stream))
        if len(ip.split('.')) != 4: return ("fail", "Not an expected ip address format")
        if len(orgmsg.arguments)>3:
            try: port=int(orgmsg.arguments[3])
            except Exception as e: return ("fail", "... Exception %s" % e)
        else: port=None

        if string.lower(identifier) == "meta":
            self.b.config_meta_output(beams=stream,dest_ip_str=ip,dest_port=port, issue_spead=False)
        if string.lower(identifier) == "data":
            self.b.config_udp_output(beams=stream,dest_ip_str=ip,dest_port=port, issue_spead=False)
        time.sleep(3)
        return ("ok",
        "data %s:%i"%(self.b.config['bf_rx_udp_ip_str_beam%d'%self.b.beam2index(stream)[0]], self.b.config['bf_rx_udp_port_beam%d'%self.b.beam2index(stream)[0]]),
        "meta %s:%i"%(self.b.config['bf_rx_meta_ip_str_beam%d'%self.b.beam2index(stream)[0]], self.b.config['bf_rx_udp_port_beam%d'%self.b.beam2index(stream)[0]])
        )

    @return_reply(Str(),Str())
    def request_tx_start(self, sock, orgmsg):
        """Start transmission to the given IP address and port, or use the defaults from the config file if not specified. The first argument should be the IP address in dotted-quad notation. The second is the port."""
        if self.c is None:
            return ("fail","... you haven't connected yet!")
        # default assumption will be correlator output
        beam=None
        dest_ip_str=None
        dest_port=None

        if len(orgmsg.arguments)>2:
            # beamformer port
            try: dest_port=int(orgmsg.arguments[2])
            except Exception as e: return ("fail", "... %s" % e)

        if len(orgmsg.arguments)>1:
            # second argument can be either port of ip
            if (len(orgmsg.arguments[1].split('.')) == 4) and (self.b is not None): # ip address
                dest_ip_str=orgmsg.arguments[1]
            else:
                try: dest_port=int(orgmsg.arguments[1])
                except Exception as e: return ("fail", "... %s" % e)

        if len(orgmsg.arguments)>0:
            # first argument can be either stream name or ip
            if len(orgmsg.arguments[0].split('.')) == 4: # ip address
                dest_ip_str=orgmsg.arguments[0]
            elif (self.b is None): return ("fail","... no beamformer available!")
            elif (self.b is not None): # stream name = beam name
                beam=orgmsg.arguments[0]
                if not beam in self.b.get_beams():
                    self.reply_inform(sock, katcp.Message.inform(orgmsg.name, "Name %s not a known beam, assuming correlator output"%(beam)),orgmsg)
                    beam=None
        try:
            if (self.b is not None) and (beam is not None):
                self.b.config_meta_output(beams=beam,dest_ip_str=dest_ip_str,dest_port=dest_port, issue_spead=False)
                self.b.config_udp_output(beams=beam,dest_ip_str=dest_ip_str,dest_port=dest_port, issue_spead=False)
                self.b.spead_issue_all(beams=beam, from_fpga=False)
                time.sleep(1) # allow little time for meta data issue to finish
                self.b.tx_start(beams=beam)
                return ("ok",
                "data %s:%i"%(self.b.config['bf_rx_udp_ip_str_beam%d'%self.b.beam2index(beam)[0]], self.b.config['bf_rx_udp_port_beam%d'%self.b.beam2index(beam)[0]]),
                "meta %s:%i"%(self.b.config['bf_rx_meta_ip_str_beam%d'%self.b.beam2index(beam)[0]], self.b.config['bf_rx_udp_port_beam%d'%self.b.beam2index(beam)[0]])
                )
            else:
                self.c.config_udp_output(dest_ip_str=dest_ip_str,dest_port=dest_port)
                self.c.spead_issue_all()
                self.c.tx_start()
                return ("ok",
                "data %s:%i"%(self.c.config['rx_udp_ip_str'], self.c.config['rx_udp_port']),
                "meta %s:%i"%(self.c.config['rx_meta_ip_str'], self.c.config['rx_udp_port'])
                )
        except corr.bf_functions.fbfException as be:
            return ("fail", "... %s" % be.errmsg)
        except Exception as e:
            return ("fail", "... %s" % e)

#     @request()
    @return_reply(Str())
    def request_spead_issue(self, sock, orgmsg):
        """Issue the SPEAD metadata so that the receiver can interpret the data stream.  If a beam name is specified the SPEAD metadata is issued to the requested beam, else it is issued to the correlator stream"""
        if self.c is None:
            return ("fail","... you haven't connected yet!")

        if len(orgmsg.arguments)>0:
            # issue beamformer spead metadata
            beam = orgmsg.arguments[0]
            if self.b is None:
                return ("fail","... no beams available!")
            try:
                self.b.spead_issue_all(beam)
                return ("ok",
                "metadata sent to %s:%i"%(self.b.config['bf_rx_meta_ip_str_beam%d'%self.b.beam2index(beam)[0]], self.b.config['bf_rx_udp_port_beam%d'%self.b.beam2index(beam)[0]])
                )
            except corr.bf_functions.fbfException as be:
                return ("fail", "... %s" % be.errmsg)
            except Exception as e:
                return ("fail","Couldn't complete the request. Something broke. Check the log.")
        else:
            # issue correlator spead metadata
            try:
                self.c.spead_issue_all()
                return ("ok",
                "metadata sent to %s:%i"%(self.c.config['rx_meta_ip_str'],self.c.config['rx_udp_port'])
                )
            except:
                return ("fail","Something broke. Check the log.")

    @return_reply()
    def request_tx_stop(self, sock, orgmsg):
        """Stop transmission to the IP given in the config file."""
        if self.c is None:
            return ("fail","... you haven't connected yet!")
        if len(orgmsg.arguments)>0:
            if self.b is None: return ('fail', '... stream specification not available in correlator mode')
            else:
                # beamformer tx-stop
                stream = orgmsg.arguments[0]
                try:
                    if stream in self.b.get_beams(): # stop beamformer output
                        self.reply_inform(sock, katcp.Message.inform(orgmsg.name, "Stop beamformer stream %s"%stream),orgmsg)
                        self.b.tx_stop(beams=stream)
                        return ("ok",)
                    else: # default -- correlator status in beamformer mode
                        self.reply_inform(sock, katcp.Message.inform(orgmsg.name, "Stop correlator stream %s"%stream),orgmsg)
                        self.c.tx_stop()
                        return ("ok",)
                except corr.bf_functions.fbfException as be:
                    return ("fail", "... %s" % be.errmsg)
                except Exception as e:
                    return ("fail", "... %s" % e)
        else:
            # correlator tx-stop
            self.reply_inform(sock, katcp.Message.inform(orgmsg.name, "Stop correlator"),orgmsg)
            try:
                self.c.tx_stop()
                return ("ok",)
            except:
                return ("fail","Something broke. Check the log.")

    @return_reply(Str())
    def request_tx_status(self, sock, orgmsg):
        """Check the TX status. Returns enabled or disabled."""
        if self.c is None:
            return ("fail","... you haven't connected yet!")
        if len(orgmsg.arguments)>0:
            if self.b is None: return ('fail', '... stream specification not available in correlator mode')
            else:
                # beamformer tx-status
                stream = orgmsg.arguments[0]
                try:
                    if stream in self.b.get_beams(): # beamformer status
                        self.reply_inform(sock, katcp.Message.inform(orgmsg.name, "Beamformer status for stream %s"%stream),orgmsg)
                        if self.b.tx_status_get(stream): return("ok","enabled")
                        else: return("ok","disabled")
                    else: # default -- correlator status in beamformer mode
                        self.reply_inform(sock, katcp.Message.inform(orgmsg.name, "Correlator status for stream %s"%stream),orgmsg)
                        if self.c.tx_status_get(): return("ok","enabled")
                        else: return("ok","disabled")
                except corr.bf_functions.fbfException as be:
                    return ("fail", "... %s" % be.errmsg)
                except Exception as e:
                    return ("fail","Couldn't complete the request. Something broke. Check the log.")
        else:
            # correlator tx-status
            self.reply_inform(sock, katcp.Message.inform(orgmsg.name, "Correlator status"),orgmsg)
            try:
                if self.c.tx_status_get(): return("ok","enabled")
                else: return("ok","disabled")
            except:
                return ("fail","Couldn't complete the request. Something broke. Check the log.")

    @request(include_msg=True)
    def request_check_sys(self, sock, orgmsg):
        """Checks system health. Returns health tree informs for each engine in the system."""
        if self.c is None:
            return katcp.Message.reply(orgmsg.name,"fail","... you haven't connected yet!")
        try:
            stat=self.c.check_all(details=True)
            for l,v in stat.iteritems():
                ret_line=[]
                for k,s in v.iteritems():
                    ret_line.append('%s:%s'%(k,s)) 
                self.reply_inform(sock, katcp.Message.inform(orgmsg.name,str(l),*ret_line),orgmsg)
            return katcp.Message.reply(orgmsg.name,"ok",len(stat))
        except:
            return katcp.Message.reply(orgmsg.name,"fail","Something broke spectacularly and the check didn't complete. Scrutinise the log.")

    @request()
    @return_reply(Int(min=0))
    def request_resync(self, sock):
        """Rearms the system. Returns the time at which the system was synch'd in ms since unix epoch."""
        if self.c is None:
            return ("fail","... you haven't connected yet!")
        try:
            time=self.c.arm()
            # currently the correlator has no concept of the beamformer
            # when the correlator label_input has been updated and a beamformer is known, the SPEAD metadata for the beamformer should be re-issued as well
            # default is to issue to all beams
            if self.b is not None: self.b.spead_time_meta_issue()
            return ("ok",(time*1000))
        except:
            return ("fail",-1)

    def request_get_adc_snapshots(self, sock, orgmsg):
        """Grabs a snapshot of data from the specified antennas. 
            \n@Param integer Sync to 1PPS (ie align all snapshots). Note that this could cost a bit of time as we wait for the next 1PPS. 
            \n@Param integer Wait for ADC level of trigger_level to capture transients.
            \n@Params list of antenna strings.
            \n@reply str antenna name.
            \n@reply int timestamp (unix seconds since epoch) of first sample.
            \n@reply int n_samples captured since trigger."""

        if self.c is None:
            return katcp.Message.reply(orgmsg.name,"fail","... you haven't connected yet!")
        if len(orgmsg.arguments)<3: 
            return katcp.Message.reply(orgmsg.name,"fail","... you didn't specify enough arguments.")
        try:
            sync_to_pps=bool(int(orgmsg.arguments[0]))
            trig_level=int(orgmsg.arguments[1])
            ant_strs=orgmsg.arguments[2:]
            for ant_str in ant_strs:
                if not ant_str in self.c.config._get_ant_mapping_list(): 
                    return katcp.Message.reply(orgmsg.name,"fail","Antenna not found. Valid entries are %s."%str(self.c.config._get_ant_mapping_list()))
            snap_data=self.c.get_adc_snapshots(ant_strs,trig_level=trig_level,sync_to_pps=sync_to_pps)
            for ant_str,data in snap_data.iteritems():
                self.reply_inform(sock,katcp.Message.inform(orgmsg.name,ant_str,str(data['timestamp']*1000),str(data['offset']),*data['data']),orgmsg)
            return katcp.Message.reply(orgmsg.name,'ok',str(len(snap_data)))
        except:
            return katcp.Message.reply(orgmsg.name,"fail","something broke. sorry.")

    @request(Str(),include_msg=True)
    def request_get_adc_snapshot(self, sock, orgmsg, ant_str):
        """Grabs a snapshot of data from the antenna specified."""
        if self.c is None:
            return katcp.Message.reply(orgmsg.name,"fail","... you haven't connected yet!")
        try:
            if not ant_str in self.c.config._get_ant_mapping_list(): 
                return katcp.Message.reply(orgmsg.name,"fail","Antenna not found. Valid entries are %s."%str(self.c.config._get_ant_mapping_list()))
            unpackedBytes=self.c.get_adc_snapshots([ant_str])[ant_str]['data']
            return katcp.Message.reply(orgmsg.name,'ok',*unpackedBytes)
            #return katcp.Message.reply(orgmsg.name,'ok','Awaiting rewrite!')
        except:
            return katcp.Message.reply(orgmsg.name,'fail',"something broke. oops.")

    @request(Str(),Int(default=1),include_msg=True)
    def request_get_quant_snapshot(self, sock, orgmsg, ant_str, n_spectra):
        """Grabs a snapshot of data from the quantiser for antenna specified. Optional: number of spectra to grab (default 1)."""
        #print 'Trying to get %i spectra.'%n_spectra
        if self.c is None:
            return katcp.Message.reply(orgmsg.name,"fail","... you haven't connected yet!")
        try:
            if not (ant_str in self.c.config._get_ant_mapping_list()): 
                return katcp.Message.reply(orgmsg.name,"fail","Antenna not found. Valid entries are: %s"%str(self.c.config._get_ant_mapping_list()))
            unpackedBytes=self.c.get_quant_snapshot(ant_str,n_spectra)
            print 'N spectra: %i.'%n_spectra
            print unpackedBytes
            if n_spectra == 1: 
                self.reply_inform(sock, katcp.Message.inform(orgmsg.name,*(['%i+%ij'%(val.real,val.imag) for val in unpackedBytes[0]])),orgmsg)
            elif n_spectra >1:
                for s_n,spectrum in enumerate(unpackedBytes):
                    #print 'Sending inform %i:'%s,unpackedBytes[s]
                    print 'trying to send the array:', ['%i+%ij'%(val.real,val.imag) for val in unpackedBytes[0][s_n]]
                    self.reply_inform(sock, katcp.Message.inform(orgmsg.name,*(['%i+%ij'%(val.real,val.imag) for val in unpackedBytes[0][s_n]])),orgmsg)
            else:
                raise RuntimeError("Please specify the number of spectra to be greater than zero!")
            return katcp.Message.reply(orgmsg.name,'ok',str(n_spectra))
        except:
            return katcp.Message.reply(orgmsg.name,'fail',"something broke. darn.")

    @request(Float(min=0))
    @return_reply(Float())
    def request_acc_time(self, sock, acc_time):
        """Set the accumulation time in seconds (float)."""
        if self.c is None:
            return ("fail","... you haven't connected yet!")
        try:
            running = self.c.tx_status_get()
            if running:
                self.c.tx_stop()
            act_period=self.c.acc_time_set(acc_time)
            print 'Set act time to %f'%act_period
            if running:
                self.c.tx_start()
            return ("ok",act_period)
        except:
            return ("fail","Something broke spectacularly and the request didn't complete. Scrutinise the log.")

    @request(include_msg=True)
    @return_reply(Int())
    def request_get_input_levs(self, sock, orgmsg):
        """Get the current RF input levels to the DBE in dBm."""
        if self.c is None:
            return ("fail","... you haven't connected yet!")
        amps=self.c.adc_amplitudes_get()
        for ant_str,ampl in amps.iteritems():
#            rf_level=amps[i]['rms_dbm'] - self.c.rf_status_get(i)[1] 
            if self.c.feng_status_get(ant_str)['adc_disabled']==True:
                stat = 'disabled'
            elif ampl['low_level_warn']==True:
                stat = 'low'
            elif ampl['high_level_warn']==True:
                stat = 'high'
            else:
                stat = 'ok'
            self.reply_inform(sock, katcp.Message.inform(orgmsg.name,ant_str,"%2.2f"%ampl['input_rms_dbm'],stat),orgmsg)
        return ("ok", len(amps))

    @request(include_msg=True)
    @return_reply(Int())
    def request_get_ant_status(self, sock, orgmsg):
        """Decode and report the status of all connected F engines. This will automatically clear the registers after the readback."""
        if self.c is None:
            return ("fail","... you haven't connected yet!")
        fstat = self.c.feng_status_get_all()
        self.c.rst_fstatus()
        for i in fstat:
            out_str=[]
            for ent in fstat[i]: 
                out_str.append(str(ent))
                out_str.append(str(fstat[i][ent]))
            self.reply_inform(sock, katcp.Message.inform(orgmsg.name,i,*out_str),orgmsg)
        return ("ok", len(fstat))

    @request(Str(),include_msg=True)
    def request_eq_get(self, sock, orgmsg, ant_str):
        """Get the current EQ configuration."""
        if self.c is None:
            return katcp.Message.reply(orgmsg.name,"fail","... you haven't connected yet!")
        if not ant_str in self.c.config._get_ant_mapping_list():
            return katcp.Message.reply(orgmsg.name,"fail","Antenna not found. Valid entries are %s."%str(self.c.config._get_ant_mapping_list()))
        eq=self.c.eq_spectrum_get(ant_str)
        return katcp.Message.reply(orgmsg.name,'ok',*eq)

    def request_eq_set(self, sock, orgmsg):
        """Set the current EQ configuration for a given antenna. ?eq-set 0x 1123+456j 555+666j 987+765j..."""
        if self.c is None:
            return katcp.Message.reply(orgmsg.name,"fail","... you haven't connected yet!")
        ant_str=orgmsg.arguments[0]
        if not ant_str in self.c.config._get_ant_mapping_list():
            return katcp.Message.reply(orgmsg.name,"fail","Antenna not found. Valid entries are %s."%str(self.c.config._get_ant_mapping_list()))

        eq_coeffs=[]
        if len(orgmsg.arguments) == 2: #+1 to account for antenna label, assume single number across entire band
            self.c.eq_spectrum_set(ant_str,init_poly=[eval(orgmsg.arguments[1])])
            return katcp.Message.reply(orgmsg.name,'ok',"Set all coefficients to %i."%eval(orgmsg.arguments[1]))
        elif len(orgmsg.arguments) != (self.c.config['n_chans']+1): #+1 to account for antenna label
            return katcp.Message.reply(orgmsg.name,"fail","Sorry, you didn't specify the right number of coefficients (expecting %i, got %i)."%(self.c.config['n_chans'],len(orgmsg.arguments)-1))
        else:
            for arg in orgmsg.arguments[1:]:
                eq_coeffs.append(eval(arg))
            self.c.eq_spectrum_set(ant_str,init_coeffs=eq_coeffs)
            return katcp.Message.reply(orgmsg.name,'ok')

    def request_fr_delay_set(self, sock, orgmsg):
        """Set the fringe rate and delay compensation config for a given antenna. Parms: antpol, fringe_offset (degrees), fr_rate (Hz), delay (seconds), delay rate, load_time (Unix seconds), <ignore check>. If there is a seventh argument, don't do any checks to see if things loaded properly. If the load time is negative, load asap."""
        if self.c is None:
            return katcp.Message.reply(orgmsg.name,"fail","... you haven't connected yet!")
        ant_str=orgmsg.arguments[0]
        if not ant_str in self.c.config._get_ant_mapping_list(): 
            return katcp.Message.reply(orgmsg.name,"fail","Antenna not found. Valid entries are %s."%str(self.c.config._get_ant_mapping_list()))

        fr_offset   =float(orgmsg.arguments[1])
        fr_rate     =float(orgmsg.arguments[2])
        delay       =float(orgmsg.arguments[3])
        del_rate    =float(orgmsg.arguments[4])
        ld_time     =float(orgmsg.arguments[5])

        if len(orgmsg.arguments)>6:
            ld_check=False
        #    print 'Ignoring load check.'
        else: 
            ld_check=True
        #    print 'Check for correct load.'

        stat = self.c.fr_delay_set(ant_str,fringe_phase=fr_offset,fringe_rate=fr_rate,delay=delay,delay_rate=del_rate,ld_time=ld_time,ld_check=ld_check)
        out_str=[]
        for ent in stat: 
            out_str.append(str(ent))
            out_str.append("%12.10e"%(stat[ent]))

        return katcp.Message.reply(orgmsg.name,'ok',*out_str)


    @request(Str(), Float(default=-1), Float(default=-1), include_msg=True)
    @return_reply(Float(), Float())
    def request_beam_passband(self, sock, orgmsg, beam, bw, cf):
        """Setup of beamformer output passband. Please specify a beam name to return the current bandwidth and centre frequency in Hz. Alternatively, specify a beam name, bandwidth and centre frequency in Hz to set the beamformer output passband. The closest actual bandwidth and centre frequency achievable will be returned."""
        if self.b is None:
            return ("fail","... beamformer functionality only!")

        if bw >= 0 and cf >= 0:
            try:
                self.b.set_passband(beams=beam, bandwidth=bw, centre_frequency=cf)
            except corr.bf_functions.fbfException as be:
                return ("fail", "... %s" % be.errmsg)
            except Exception as e:
                return ("fail", "... %s" % e)
        elif (bw*cf < 0): return ("fail", "... require both bandwidth and center frequency to be specified")

        try:
            cf, bw = self.b.get_passband(beam=beam)
            return ("ok", bw, cf)
        except:
            return ("fail", "... unknown beam name %s" % orgmsg.arguments[0])

    @request(Str(), Str(), include_msg=True)
    def request_weights_get(self, sock, orgmsg, beam, ant_str):
        """Get the current beamformer weights. Params: beam, ant_str"""
        if self.c is None or self.b is None:
            return katcp.Message.reply(orgmsg.name,"fail","... you haven't connected yet!")
        if not ant_str in self.c.config._get_ant_mapping_list():
            return katcp.Message.reply(orgmsg.name,"fail","Antenna not found. Valid entries are %s."%str(self.c.config._get_ant_mapping_list()))
        if not beam in self.b.get_beams():
            return katcp.Message.reply(orgmsg.name,"fail","Unknown beam name. Valid entries are %s."%str(self.b.get_beams()))
        try:
          weights = self.b.cal_spectrum_get(beam=beam, ant_str=ant_str)
          return katcp.Message.reply(orgmsg.name,'ok',*weights)
        except corr.bf_functions.fbfException as be:
            return ("fail", "... %s" % be.errmsg)
        except Exception as e:
            return ("fail", "... %s" % e)

    def request_weights_set(self, sock, orgmsg):
        """Set the weights for an input to a selected beam. ?weights-set bf0 0x 1123+456j 555+666j 987+765j..."""
        if self.c is None or self.b is None:
            return katcp.Message.reply(orgmsg.name,"fail","... you haven't connected yet!")
        beam=orgmsg.arguments[0]
        if not beam in self.b.get_beams():
            return katcp.Message.reply(orgmsg.name,"fail","Unknown beam name. Valid entries are %s."%str(self.b.get_beams()))
        ant_str=orgmsg.arguments[1]
        if not ant_str in self.c.config._get_ant_mapping_list():
            return katcp.Message.reply(orgmsg.name,"fail","Antenna not found. Valid entries are %s."%str(self.c.config._get_ant_mapping_list()))
        try:
            bw_coeffs=[]
            if len(orgmsg.arguments) == 3: #+2 to account for beam name and antenna label, assume single number across entire band
                self.b.cal_spectrum_set(beam=beam, ant_str=ant_str,init_poly=[eval(orgmsg.arguments[2])])
                return katcp.Message.reply(orgmsg.name,'ok',"Set all coefficients to", eval(orgmsg.arguments[2]))
            elif len(orgmsg.arguments) != (self.c.config['n_chans']+2): #+2 to account for beam name and antenna label
                return katcp.Message.reply(orgmsg.name,"fail","Sorry, you didn't specify the right number of coefficients (expecting %i, got %i)."%(self.c.config['n_chans'],len(orgmsg.arguments)-2))
            else:
                for arg in orgmsg.arguments[2:]:
                    bw_coeffs.append(eval(arg))
                self.b.cal_spectrum_set(beam=beam, ant_str=ant_str,init_coeffs=bw_coeffs)
                return katcp.Message.reply(orgmsg.name,'ok')
        except corr.bf_functions.fbfException as be:
            return ("fail", "... %s" % be.errmsg)
        except Exception as e:
            return ("fail", "... %s" % e)

if __name__ == "__main__":

    usage = "usage: %prog [options]"
    parser = OptionParser(usage=usage)
    parser.add_option('-a', '--host', dest='host', type="string", default="", metavar='HOST',
                      help='listen to HOST (default="" - all hosts)')
    parser.add_option('-p', '--port', dest='port', type=long, default=1235, metavar='N',
                      help='attach to port N (default=1235)')
    (opts, args) = parser.parse_args()

    print "Server listening on port %d, Ctrl-C to terminate server" % opts.port
    restart_queue = Queue.Queue()
    server = DeviceExampleServer(opts.host, opts.port)
    server.set_restart_queue(restart_queue)

    server.start()
    print "Started."

    try:
        while True:
            try:
                device = restart_queue.get(timeout=0.5)
            except Queue.Empty:
                device = None
            if device is not None:
                print "Stopping ..."
                device.stop()
                device.join()
                print "Restarting ..."
                device.start()
                print "Started."
    except KeyboardInterrupt:
        print "Shutting down ..."
        server.stop()
        server.join()
