from setuptools import setup, find_packages

setup(
    name='BottleneckedHTTPAPIServer',
    version='0.1.0',
    description='Convenience APIs for executing jobs on a single threaded bottlenecked environment, and creating a corresponding HTTP API server.',
    author='Louis, Chau Yu Hei',
    author_email='louis321yh@gmail.com',
    license="Apache License, Version 2.0",
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    install_requires=[
    ],
    entry_points={
    },
    classifiers=[
        'Programming Language :: Python :: 3',
        'Operating System :: Unix',
    ],
)