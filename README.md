[![Build Status][travis-image]][travis-url]
# apt-clone

apt-clone lets you create "state" files of all installed packages for your Debian/Ubuntu systems
that can be restored on freshly installed systems (or containers) or into a directory. 

Use cases:
- clone server package selection and restore on fallback system
- backup system state to be able to restore in case of emergency

## Usage

### Create a clone (apt state backup)
```
$ sudo apt-clone clone ~/myhost
```
will create an ~/myhost.apt-clone.tar.gz.

### Get info about the clone
```
$ apt-clone info ~/myhost.apt-clone.tar.gz
Hostname: top
Arch: amd64
Distro: wily
Meta: ubuntu-desktop
Installed: 3308 pkgs (1469 automatic)
Date: Fri Nov  6 23:06:35 2015
```

### Restore the clone

The restore will override your existing /etc/apt/sources.list and will install/remove packages.
So be careful!

`
$ sudo apt-clone restore ~/myhost.apt-clone.tar.gz
`
Note that you can give the option `--destination /some/dir` and it will debootstrap the clone into this directory.

[travis-image]: https://travis-ci.org/mvo5/apt-clone.svg?branch=master
[travis-url]: https://travis-ci.org/mvo5/apt-clone

