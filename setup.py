from setuptools import setup, find_packages

setup(
    name='ab_selenium_wrapper',
    version='0.1',
    packages=find_packages(),
    install_requires=[
        'selenium',
        'selenium-stealth',
        'requests',
    ],
    description='A wrapper for Selenium with added features',
    author='TheAB',
    author_email='oscarbascon@gmail.com',
    url='https://github.com/TheAB1/ab-selenium-wrapper',
)
