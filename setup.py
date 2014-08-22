#!/usr/bin/env python

from setuptools import setup

setup(
    name='newznabbalancer',
    version="0.1",
    description='balance your requests over different newznab providers',
    author='Jayme',
    author_email='tuxnet@gmail.com',
    url='https://github.com/jayme-github/newznabbalancer',
    packages=['newznabbalancer'],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
    ],
    scripts = ['nnb-server'],
)
