# vectis - do useful things in a virtual machine
# Copyright © 2015-2016 Simon McVittie
# SPDX-License-Identifier: GPL-2.0+
# (see vectis/__init__.py)

AC_PREREQ([2.69])

AC_INIT([vectis],
    m4_esyscmd([build-aux/git-version-gen .tarball-version]),
    [https://github.com/smcv/vectis/issues], [],
    [https://git.pseudorandom.co.uk/vectis.git])

AC_CONFIG_SRCDIR([vectis/__main__.py])
AC_CONFIG_AUX_DIR([build-aux])
AC_CONFIG_MACRO_DIR([m4])
AC_REQUIRE_AUX_FILE([tap-driver.sh])

AC_CHECK_PROG([PYFLAKES], [pyflakes3], [pyflakes3], [false])
AC_PROG_MKDIR_P

AM_INIT_AUTOMAKE([
    1.15
    dist-xz
    foreign
    no-dist-gzip
    parallel-tests
    subdir-objects
])
AM_MAINTAINER_MODE([enable])
AM_SILENT_RULES
AM_PATH_PYTHON([3])
AX_PYTHON_MODULE([tap])

AC_PROG_SED

m4_pattern_forbid([^AX_],
    [Unexpanded AX_ macro found. Please install GNU autoconf-archive])

AX_GENERATE_CHANGELOG

AC_CONFIG_FILES([Makefile])
AC_OUTPUT

# vim:set sw=4 sts=4 et:
