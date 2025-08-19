# -*- coding: utf-8 -*-

from setuptools import setup, find_packages


with open('README.md') as f:
    readme = f.read()

with open('LICENSE') as f:
    license = f.read()

setup(
    name='ssg',
    version='0.1.0',
    description='Static site generator',
    long_description=readme,
    author='Jon Hurst',
    author_email='jon.a@hursts.org.uk',
    url='https://github.com/JonHurst/ssg',
    license=license,
    packages=find_packages(exclude=('tests', 'docs')),
    entry_points={
        'console_scripts': ['ssg=ssg.main:main'],
    },
    install_requires=[
        'Jinja2',
        'imagesize',
        'commonmark',
    ],
    extras_require={
        "testing": ['pyfakefs'],
    },
)
