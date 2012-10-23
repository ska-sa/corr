from distutils.core import setup, Extension
import os, sys, glob

__version__ = '0.7.1'

setup(name = 'corr',
    version = __version__,
    description = 'Interfaces to CASPER correlators',
    long_description = 'Provides interfaces to CASPER hardware and functions to configure packetised correlators.',
    license = 'GPL',
    author = 'Jason Manley',
    author_email = 'jason_manley at hotmail.com',
    url = 'http://pypi.python.org/pypi/corr',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Operating System :: OS Independent',
        'License :: OSI Approved :: GNU General Public License (GPL)',
        'Topic :: Scientific/Engineering :: Astronomy',
        'Topic :: Software Development :: Libraries :: Python Modules',
        ],
    requires=['katcp', 'pylab','matplotlib','iniparse', 'numpy', 'spead', 'curses', 'construct'],
    provides=['corr'],
    package_dir = {'corr':'src'},
    packages = ['corr'],
    scripts=glob.glob('scripts/*'),
    data_files=[('/etc/corr',['etc/default']),
                #('/var/run/corr',['support_files/sync_time'])
                ]
)

