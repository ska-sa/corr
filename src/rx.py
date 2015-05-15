"""Code for receiving data from correlators and storing in HDF5 file. Will also send a copy to realtime signal display."""
"""Revs:
2011-12-12  JRM Metadata propagation to SD.
                Datatype propagation through to SD
                min/max value logging (was not scaling back).
                Loggin: SPEAD and RX levels.
                Timestamps to SD.
"""

import threading
import numpy as np
import spead64_48 as spead
import logging
import sys
import time
import h5py
import corr

class CorrRx(threading.Thread):
    def __init__(self, mode = 'cont', port=7148, log_handler = None, log_level = logging.INFO, spead_log_level = logging.WARN, **kwargs):
        if log_handler == None:
            log_handler = corr.log_handlers.DebugLogHandler(100)
        self.log_handler = log_handler
        self.logger = logging.getLogger('rx')
        self.logger.addHandler(self.log_handler)
        self.logger.setLevel(log_level)
        spead.logging.getLogger().setLevel(spead_log_level)

        if mode == 'cont':
            self._target = self.rx_cont
        elif mode=='inter':
            self._target = self.rx_inter
        else:
            raise RuntimeError('Mode not understood. Expecting inter or cont.')
        self._kwargs = kwargs
        #print kwargs
        threading.Thread.__init__(self)

    def run(self):
        #print 'starting target with kwargs ',self._kwargs
        self._target(**self._kwargs)

    def rx_cont(self,data_port=7148, sd_ip='127.0.0.1', sd_port=7149,acc_scale=True, filename=None,**kwargs):
        logger=self.logger
        logger.info("Data reception on port %i."%data_port)
        rx = spead.TransportUDPrx(data_port, pkt_count=1024, buffer_size=51200000)
        logger.info("Sending Signal Display data to %s:%i."%(sd_ip,sd_port))
        tx_sd = spead.Transmitter(spead.TransportUDPtx(sd_ip, sd_port))
        ig = spead.ItemGroup()
        ig_sd = spead.ItemGroup()
        if filename == None:
            filename=str(int(time.time())) + ".synth.h5"
        logger.info("Starting file %s."%(filename))
        f = h5py.File(filename, mode="w")
        data_ds = None
        ts_ds = None
        idx = 0
        dump_size = 0
        datasets = {}
        datasets_index = {}
        meta_required = ['n_chans','bandwidth','n_bls','n_xengs','center_freq','bls_ordering']
         # we need these bits of meta data before being able to assemble and transmit signal display data
        meta_desired = ['n_accs']
        meta = {}
        for heap in spead.iterheaps(rx):
            ig.update(heap)
            logger.debug("PROCESSING HEAP idx(%i) cnt(%i) @ %.4f" % (idx, heap.heap_cnt, time.time()))
            for name in ig.keys():
                item = ig.get_item(name)
                if not item._changed and datasets.has_key(name): continue # the item is not marked as changed, and we have a record for it
                if name in meta_desired:
                    meta[name] = ig[name]
                if name in meta_required:
                    meta[name] = ig[name]
                    meta_required.pop(meta_required.index(name))
                    if len(meta_required) == 0:
                        #sd_frame = np.zeros((meta['n_chans'],meta['n_bls'],2),dtype=np.float32)
                        logger.info("Got all required metadata. Expecting data frame shape of %i %i %i"%(meta['n_chans'],meta['n_bls'],2))
                        meta_required = ['n_chans','bandwidth','n_bls','n_xengs','center_freq','bls_ordering']
                        ig_sd = spead.ItemGroup()
                        for meta_item in meta_required:
                          ig_sd.add_item(
                            name=ig.get_item(meta_item).name,
                            id=ig.get_item(meta_item).id,
                            description=ig.get_item(meta_item).description,
                            #shape=ig.get_item(meta_item).shape,
                            #fmt=ig.get_item(meta_item).format,
                            init_val=ig.get_item(meta_item).get_value())
                        tx_sd.send_heap(ig_sd.get_heap())

                if not datasets.has_key(name):
                 # check to see if we have encountered this type before
                    shape = ig[name].shape if item.shape == -1 else item.shape
                    dtype = np.dtype(type(ig[name])) if shape == [] else item.dtype
                    if dtype is None: dtype = ig[name].dtype
                     # if we can't get a dtype from the descriptor try and get one from the value
                    logger.info("Creating dataset for %s (%s,%s)."%(str(name),str(shape),str(dtype)))
                    f.create_dataset(name,[1] + ([] if list(shape) == [1] else list(shape)), maxshape=[None] + ([] if list(shape) == [1] else list(shape)), dtype=dtype)
                    dump_size += np.multiply.reduce(shape) * dtype.itemsize
                    datasets[name] = f[name]
                    datasets_index[name] = 0
                    if not item._changed: continue
                     # if we built from and empty descriptor
                else:
                    logger.info("Adding %s to dataset. New size is %i."%(name,datasets_index[name]+1))
                    f[name].resize(datasets_index[name]+1, axis=0)
                if name.startswith("xeng_raw"):
                    sd_timestamp = ig['sync_time'] + (ig['timestamp'] / float(ig['scale_factor_timestamp']))
                    #logger.info("SD Timestamp: %f (%s)."%(sd_timestamp,time.ctime(sd_timestamp)))

                    scale_factor=float(meta['n_accs'] if (meta.has_key('n_accs') and acc_scale) else 1)
                    scaled_data = (ig[name]/scale_factor).astype(np.float32)

                     # reinit the group to force meta data resend
                    ig_sd = spead.ItemGroup()
                    ig_sd.add_item(name=('sd_data'),
                                    id=(0x3501),
                                    description="Combined raw data from all x engines.",
                                    ndarray=(scaled_data.dtype,scaled_data.shape))
                    ig_sd.add_item(name=('sd_timestamp'),
                                    id=0x3502,
                                    description='Timestamp of this sd frame in centiseconds since epoch (40 bit limitation).',
                                    init_val=sd_timestamp)
                                    #shape=[],
                                    #fmt=spead.mkfmt(('u',spead.ADDRSIZE)))
                    t_it = ig_sd.get_item('sd_data')
                    logger.debug("Added SD frame with shape %s, dtype %s"%(str(t_it.shape),str(t_it.dtype)))
                    tx_sd.send_heap(ig_sd.get_heap())

                    logger.info("Sending signal display frame with timestamp %i (%s). %s. Max: %i, Mean: %i"%(
                        sd_timestamp,
                        time.ctime(sd_timestamp),
                        "Unscaled" if not acc_scale else "Scaled by %i" % (scale_factor),
                        np.max(scaled_data),
                        np.mean(scaled_data)))
                    ig_sd['sd_data'] = scaled_data
                    ig_sd['sd_timestamp'] = sd_timestamp * 100
                    #ig_sd['sd_timestamp'] = sd_timestamp
                    tx_sd.send_heap(ig_sd.get_heap())

                f[name][datasets_index[name]] = ig[name]
                datasets_index[name] += 1
                item._changed = False
                  # we have dealt with this item so continue...
            idx+=1

#        for (name,idx) in datasets_index.iteritems():
#            if idx == 1:
#                self.logger.info("Repacking dataset %s as an attribute as it is singular."%name)
#                f['/'].attrs[name] = f[name].value[0]
#                f.__delitem__(name)
        logger.info("Got a SPEAD end-of-stream marker. Closing File.")
        f.flush()
        f.close()
        rx.stop()
        ig_sd = None
        sd_timestamp = None
        logger.info("Files and sockets closed.")


    def rx_inter(self,data_port=7148, sd_ip='127.0.0.1', sd_port=7149, acc_scale=True, filename=None, **kwargs):
        '''
        Process SPEAD data from X engines and forward it to the SD.
        '''
        print 'WARNING: This function is not yet tested. YMMV.'
        logger=self.logger
        logger.info("Data reception on port %i."%data_port)
        rx = spead.TransportUDPrx(data_port, pkt_count=1024, buffer_size=51200000)
        logger.info("Sending Signal Display data to %s:%i."%(sd_ip,sd_port))
        tx_sd = spead.Transmitter(spead.TransportUDPtx(sd_ip, sd_port))
        ig = spead.ItemGroup()
        ig_sd = spead.ItemGroup()
        if filename == None:
          filename=str(int(time.time())) + ".synth.h5"
        logger.info("Starting file %s."%(filename))
        f = h5py.File(filename, mode="w")
        data_ds = None
        ts_ds = None
        idx = 0
        dump_size = 0
        datasets = {}
        datasets_index = {}
        # we need these bits of meta data before being able to assemble and transmit signal display data
        meta_required = ['n_chans','n_bls','n_xengs','center_freq','bls_ordering','bandwidth']
        meta_desired = ['n_accs']
        meta = {}
        sd_frame = None
        sd_slots = None
        timestamp = None

        # log the latest timestamp for which we've stored data
        currentTimestamp = -1

        # iterate through SPEAD heaps returned by the SPEAD receiver.
        for heap in spead.iterheaps(rx):
            ig.update(heap)
            logger.debug("PROCESSING HEAP idx(%i) cnt(%i) @ %.4f" % (idx, heap.heap_cnt, time.time()))
            for name in ig.keys():
                item = ig.get_item(name)

                # the item is not marked as changed and we already have a record for it, continue
                if not item._changed and datasets.has_key(name):
                  continue
                logger.debug("PROCESSING KEY %s @ %.4f" % (name, time.time()))

                if name in meta_desired:
                    meta[name] = ig[name]

                if name in meta_required:
                  meta[name] = ig[name]
                  meta_required.pop(meta_required.index(name))
                  if len(meta_required) == 0:
                    sd_frame = np.zeros((meta['n_chans'],meta['n_bls'],2),dtype=np.float32)
                    logger.info("Got all required metadata. Initialised sd frame to shape %s"%(str(sd_frame.shape)))
                    meta_required = ['n_chans','bandwidth','n_bls','n_xengs','center_freq','bls_ordering']
                    ig_sd = spead.ItemGroup()
                    for meta_item in meta_required:
                      ig_sd.add_item(
                        name=ig.get_item(meta_item).name,
                        id=ig.get_item(meta_item).id,
                        description=ig.get_item(meta_item).description,
                        #shape=ig.get_item(meta_item).shape,
                        #fmt=ig.get_item(meta_item).format,
                        init_val=ig.get_item(meta_item).get_value())
                    tx_sd.send_heap(ig_sd.get_heap())
                    sd_slots = np.zeros(meta['n_xengs'])
                if not datasets.has_key(name):
                 # check to see if we have encountered this type before
                  shape = ig[name].shape if item.shape == -1 else item.shape
                  dtype = np.dtype(type(ig[name])) if shape == [] else item.dtype
                  if dtype is None: dtype = ig[name].dtype
                   # if we can't get a dtype from the descriptor, try and get one from the value
                  logger.info("Creating dataset for %s (%s,%s)."%(str(name),str(shape),str(dtype)))
                  f.create_dataset(name,[1] + ([] if list(shape) == [1] else list(shape)), maxshape=[None] + ([] if list(shape) == [1] else list(shape)), dtype=dtype)
                  dump_size += np.multiply.reduce(shape) * dtype.itemsize
                  datasets[name] = f[name]
                  datasets_index[name] = 0
                  # if we built from an empty descriptor
                  if not item._changed:
                    continue
                else:
                  logger.info("Adding %s to dataset. New size is %i."%(name,datasets_index[name]+1))
                  f[name].resize(datasets_index[name]+1, axis=0)

                # now we store this x engine's data for sending sd data.
                if sd_frame is not None and name.startswith("xeng_raw"):
                  xeng_id = int(name[8:])
                  sd_frame[xeng_id::meta['n_xengs']] = ig[name]
                  logger.debug('Received data for Xeng %i @ %.4f' % (xeng_id, time.time()))

                # we got a timestamp.
                if sd_frame is not None and name.startswith("timestamp"):
                  xeng_id = int(name[9:])
                  timestamp = ig['sync_time'] + (ig[name] / ig['scale_factor_timestamp']) #in seconds since unix epoch
                  localTime = time.time()
                  print "Decoded timestamp for Xeng", xeng_id, ":", timestamp, " (", time.ctime(timestamp),") @ %.4f" % localTime, " ", time.ctime(localTime), "diff(", localTime-timestamp, ")"

                  # is this timestamp in the past?
                  if currentTimestamp > timestamp:
                    errorString = "Timestamp %.2f (%s) is earlier than the current timestamp %.2f (%s). Ignoring..." % (timestamp, time.ctime(timestamp), currentTimestamp, time.ctime(currentTimestamp))
                    logger.warning(errorString)
                    continue

                  # is this a new timestamp before a complete set?
                  if (timestamp > currentTimestamp) and sd_slots.any():
                    errorString = "New timestamp %.2f from Xeng%i before previous set %.2f sent" % (timestamp, xeng_id, currentTimestamp)
                    logger.warning(errorString)
                    sd_slots = np.zeros(meta['n_xengs'])
                    sd_frame = np.zeros((ig['n_chans'],ig['n_bls'],2),dtype=sd_frame.dtype)
                    currentTimestamp = -1
                    continue

                  # is this new timestamp in the past for this X engine?
                  if timestamp <= sd_slots[xeng_id]:
                    errorString = 'Xeng%i already on timestamp %.2f but got %.2f now, THIS SHOULD NOT HAPPEN' % (xeng_id, sd_slots[xeng_id], timestamp)
                    logger.error(errorString)
                    raise RuntimeError(errorString)

                  # update our info on which integrations we have
                  sd_slots[xeng_id] = timestamp
                  currentTimestamp = timestamp

                # do we have integration data and timestamps for all the xengines? If so, send the SD frame.
                if timestamp is not None and sd_frame is not None and sd_slots is not None and sd_slots.all():
                    ig_sd = spead.ItemGroup()
                    # make sure we have the right dtype for the sd data
                    ig_sd.add_item(name=('sd_data'), id=(0x3501), description="Combined raw data from all x engines.", ndarray=(sd_frame.dtype,sd_frame.shape))
                    ig_sd.add_item(name=('sd_timestamp'), id=0x3502, description='Timestamp of this sd frame in centiseconds since epoch (40 bit limitation).', shape=[], fmt=spead.mkfmt(('u',spead.ADDRSIZE)))
                    t_it = ig_sd.get_item('sd_data')
                    logger.info("Added SD frame with shape %s, dtype %s" % (str(t_it.shape),str(t_it.dtype)))
                    scale_factor=(meta['n_accs'] if meta.has_key('n_accs') else 1)
                    logger.info("Sending signal display frame with timestamp %i (%s). %s. @ %.4f" % (timestamp, time.ctime(timestamp), "Unscaled" if not acc_scale else "Scaled by %i" % (scale_factor), time.time()))
                    ig_sd['sd_data'] = sd_frame.astype(np.float32) if not acc_scale else (sd_frame / float(scale_factor)).astype(np.float32)
                    ig_sd['sd_timestamp'] = int(timestamp * 100)
                    tx_sd.send_heap(ig_sd.get_heap())
                    # reset the arrays that hold integration data
                    sd_slots = np.zeros(meta['n_xengs'])
                    sd_frame = np.zeros((ig['n_chans'],ig['n_bls'],2),dtype=sd_frame.dtype)
                    timestamp = None

                f[name][datasets_index[name]] = ig[name]
                datasets_index[name] += 1
                item._changed = False
            idx+=1

        logger.info("Got a SPEAD end-of-stream marker. Closing File.")
        f.flush()
        f.close()
        rx.stop()
        sd_frame = None
        sd_slots = None
        ig_sd = None

