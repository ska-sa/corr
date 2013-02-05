import katcp_wrapper

def fpga_operation(fpga_list, num_threads = -1, job_function = None, *job_args):
    """Run a provided method on a list of FpgaClient objects in a specified number of threads.

    @param fpga_list: list of FpgaClient objects
    @param num_threads: how many threads should be used. Default is one per list item
    @param job_function: the function to be run - MUST take the FpgaClient object as its first argument
    @param *args: further arugments for the job_function
   
    @return a dictionary of results from the functions, keyed on FpgaClient.host
 
    """

    """
    Example:
    def xread_all_new(self, register, bram_size, offset = 0):
         import threaded
         def xread_all_thread(host):
             return host.read(register, bram_size, offset)
         vals = threaded.fpga_operation(self.xfpgas, num_threads = -1, job_function = xread_all_thread)
         rv = []
         for x in self.xfpgas: rv.append(vals[x.host])
         return rv
    """

    if job_function == None:
        raise RuntimeError("job_function == None?")
    import threading, Queue
    # thread class to perform a job from a queue
    class Corr_worker(threading.Thread):
        def __init__(self, request_queue, result_queue, job_function, *job_args):
            self.request_queue = request_queue
            self.result_queue = result_queue
            self.job = job_function
            self.job_args = job_args
            threading.Thread.__init__(self)
        def run(self):
            done = False
            while not done:
                try:
                    # get a job from the queue
                    request_host = self.request_queue.get(False)
                    # do some work
                    try:
                        result = self.job(request_host, *self.job_args)
                    except Exception as exc:
                        errstr = "Job %s internal error: %s, %s" % (self.job.func_name, type(exc), exc)
                        result = RuntimeError(errstr)
                    # put the result on the result queue
                    self.result_queue.put((request_host.host, result))
                    # and notify done
                    self.request_queue.task_done()
                except:
                    done = True
    if not isinstance(fpga_list, list):
        raise TypeError("fpga_list should be a list() of FpgaClient objects only.")
    if num_threads == -1:
        num_threads = len(fpga_list)
    # create the request and result queues
    request_queue = Queue.Queue()
    result_queue = Queue.Queue()
    # put the list items into a Thread-safe Queue
    for f in fpga_list:
        if not isinstance(f, katcp_wrapper.FpgaClient):
            raise TypeError('Currently this function only supports FpgaClient objects.')
        request_queue.put(f)
    # make as many worker threads a specified and start them off
    workers = [Corr_worker(request_queue, result_queue, job_function, *job_args) for i in range(0, num_threads)]
    for w in workers:
        w.daemon = True
        w.start()
    # join the last one to wait for completion
    request_queue.join()
    # format the result into a dictionary by host
    rv = {}
    while not result_queue.empty():
        res = result_queue.get()
        rv[res[0]] = res[1]
    return rv

