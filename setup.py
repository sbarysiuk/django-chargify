from setuptools import setup, find_packages

VERSION = (1, 0, 2)

# Dynamically calculate the version based on VERSION tuple
if len(VERSION)>2 and VERSION[2] is not None:
    str_version = "%d.%d_%s" % VERSION[:3]
else:
    str_version = "%d.%d" % VERSION[:2]

version= str_version

setup(
    name = 'django-chargify',
    version = version,
    description = "chargify",
    long_description = """This is a generic SDK for hooking up with the Chargify API""",
    author = 'Greg Doermann',
    author_email = 'gdoermann@snirk.com',
    url = 'http://github.com/gdoermann/django-chargify',
    license = 'GNU General Public License',
    platforms = ['any'],
    classifiers = ['Development Status :: 4 - Beta',
                   'Environment :: Web Environment',
                   'Intended Audience :: Developers',
                   'License :: OSI Approved :: GNU General Public License (GPL)',
                   'Operating System :: OS Independent',
                   'Programming Language :: Python',
                   'Framework :: Django'],
    packages = find_packages(),
    include_package_data = True,
)
