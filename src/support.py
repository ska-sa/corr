def gzip(filename):
    return NotImplementedError
    import gzip
    f = gzip.open(bof_file, 'rb')
    gzipped_already = True
    try:
        a = f.read()
    except:
        gzipped_already = False
    if not gzipped_already:
        tempfile = tempfile.TemporaryFile('w+b')
        gzipfile = gzip.open('dontcare', 'wb', 9, tempfile)
        gzipfile.write(f)
    f.close()
 
