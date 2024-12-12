from setuptools import setup, find_packages

setup(
    name='BottleneckedHTTPAPIServer',
    version='0.1.2',
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
    python_requires=">=3.10",
    classifiers=[
        'Programming Language :: Python :: 3',
        'Operating System :: Unix',
    ],
)