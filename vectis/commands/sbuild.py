# Copyright © 2016 Simon McVittie
# SPDX-License-Identifier: GPL-2.0+
# (see vectis/__init__.py)

import logging
import os
import shutil
import subprocess

from vectis.autopkgtest import (
        run_autopkgtest,
        )
from vectis.debuild import (
        Build,
        Buildable,
        )
from vectis.error import (
        ArgumentError,
        )
from vectis.util import (
        AtomicWriter,
        )
from vectis.worker import (
        VirtWorker,
        )

logger = logging.getLogger(__name__)

def get_dpkg_buildpackage_options(args, suite):
    argv = []

    if args._versions_since:
        argv.append('-v{}'.format(args._versions_since))

    force_parallel = args.force_parallel or suite.force_parallel

    if force_parallel:
        argv.append('-j{}'.format(force_parallel))
    elif args.parallel == 1:
        argv.append('-j1')
    elif args.parallel:
        argv.append('-J{}'.format(args.parallel))
    else:
        argv.append('-Jauto')

    for a in get_dpkg_source_options(args):
        argv.append('--source-option=' + a)

    return argv

def get_dpkg_source_options(args):
    argv = []

    if args.dpkg_source_diff_ignore is ...:
        argv.append('-i')
    elif args.dpkg_source_diff_ignore is not None:
        argv.append('-i{}'.format(
            args.dpkg_source_diff_ignore))

    for pattern in args.dpkg_source_tar_ignore:
        if pattern is ...:
            argv.append('-I')
        else:
            argv.append('-I{}'.format(pattern))

    for pattern in args.dpkg_source_extend_diff_ignore:
        argv.append('--extend-diff-ignore={}'.format(pattern))

    return argv

def _sbuild(args, buildables, *,
        archs,
        components,
        indep,
        output_builds,
        rebuild_source,
        source_only,
        storage,
        vendor,
        worker,
        extra_repositories=(),
        together=False):

    logger.info('Installing sbuild')
    worker.check_call([
        'env',
        'DEBIAN_FRONTEND=noninteractive',
        'apt-get',
        '-y',
        '--no-install-recommends',
        'install',

        'python3',
        'sbuild',
        'schroot',
        ])

    for buildable in buildables:
        logger.info('Processing: %s', buildable)

        buildable.copy_source_to(worker)

        if buildable.suite == 'UNRELEASED':
            logger.info('Replacing UNRELEASED with {}'.format(
                vendor.default_suite))
            suite = vendor.get_suite(vendor.default_suite)
        else:
            logger.info('Using suite {}'.format(buildable.suite))
            suite = vendor.get_suite(buildable.suite)

        dpkg_buildpackage_options = get_dpkg_buildpackage_options(args, suite)
        dpkg_source_options = get_dpkg_source_options(args)

        def new_build(arch, output_builds=output_builds):
            return Build(buildable, arch, worker,
                    components=components,
                    extra_repositories=extra_repositories,
                    dpkg_buildpackage_options=dpkg_buildpackage_options,
                    dpkg_source_options=dpkg_source_options,
                    output_builds=output_builds,
                    storage=storage,
                    suite=suite)

        if rebuild_source:
            new_build('source').sbuild()
        elif buildable.source_from_archive:
            # We need to get some information from the .dsc, which we do by
            # building one and throwing it away.
            new_build('source', output_builds=None).sbuild()
        elif buildable.dsc is None:
            # We're building from a directory; get a .dsc
            new_build('source').sbuild()

        if not source_only:
            buildable.select_archs(worker.dpkg_architecture, archs, indep,
                    together)

            for arch in buildable.archs:
                new_build(arch).sbuild()

        if buildable.sourceful_changes_name:
            c = os.path.join(output_builds,
                    '{}_source.changes'.format(buildable.product_prefix))
            if 'source' not in buildable.changes_produced:
                with AtomicWriter(c) as writer:
                    subprocess.check_call([
                            'mergechanges',
                            '--source',
                            buildable.sourceful_changes_name,
                            buildable.sourceful_changes_name,
                        ],
                        stdout=writer)

            buildable.merged_changes['source'] = c

        if ('all' in buildable.changes_produced and
                'source' in buildable.merged_changes):
            c = os.path.join(output_builds,
                    '{}_source+all.changes'.format(buildable.product_prefix))
            buildable.merged_changes['source+all'] = c
            with AtomicWriter(c) as writer:
                subprocess.check_call([
                    'mergechanges',
                    buildable.changes_produced['all'],
                    buildable.merged_changes['source'],
                    ], stdout=writer)

        c = os.path.join(output_builds,
                '{}_binary.changes'.format(buildable.product_prefix))

        binary_changes = []
        for k, v in buildable.changes_produced.items():
            if k != 'source':
                binary_changes.append(v)

        if len(binary_changes) > 1:
            with AtomicWriter(c) as writer:
                subprocess.check_call(['mergechanges'] + binary_changes,
                    stdout=writer)
            buildable.merged_changes['binary'] = c
        elif len(binary_changes) == 1:
            shutil.copy(binary_changes[0], c)
            buildable.merged_changes['binary'] = c
        # else it was source-only: no binary changes

        if ('source' in buildable.merged_changes and
                'binary' in buildable.merged_changes):
            c = os.path.join(output_builds,
                    '{}_source+binary.changes'.format(buildable.product_prefix))
            buildable.merged_changes['source+binary'] = c

            with AtomicWriter(c) as writer:
                subprocess.check_call([
                        'mergechanges',
                        buildable.merged_changes['source'],
                        buildable.merged_changes['binary'],
                    ],
                    stdout=writer)

def _autopkgtest(args, buildables, default_architecture, *,
        components,
        lxc_24bit_subnet,
        lxc_worker,
        lxc_worker_suite,
        mirror,
        modes,
        storage,
        vendor,
        worker_argv,
        worker_suite,
        extra_repositories=()):
    for buildable in buildables:
        source_changes = None
        source_package = None

        if 'source' in buildable.merged_changes:
            source_changes = buildable.merged_changes['source']
            logger.info('Testing source changes file %s', source_changes)
        elif buildable.source_from_archive:
            source_package = buildable.source_package
            logger.info('Testing source package %s', source_package)
        else:
            logger.warning('Unable to run autopkgtest on %s',
                    buildable.buildable)
            continue

        if buildable.dsc is not None and 'testsuite' not in buildable.dsc:
            logger.info('No autopkgtests available')
            continue

        test_architectures = []

        for arch in buildable.archs:
            if arch != 'all' and arch != 'source':
                test_architectures.append(arch)

        if 'all' in buildable.archs and not test_architectures:
            test_architectures.append(default_architecture)

        logger.info('Testing on architectures: %r', test_architectures)

        for architecture in test_architectures:
            run_autopkgtest(
                    architecture=architecture,
                    binaries=(buildable.merged_changes['binary'],),
                    components=components,
                    extra_repositories=extra_repositories,
                    lxc_24bit_subnet=lxc_24bit_subnet,
                    lxc_worker=lxc_worker,
                    lxc_worker_suite=lxc_worker_suite,
                    mirror=mirror,
                    modes=modes,
                    source_changes=source_changes,
                    source_package=source_package,
                    storage=storage,
                    suite=vendor.get_suite(buildable.suite),
                    vendor=vendor,
                    worker_argv=worker_argv,
                    worker_suite=worker_suite,
                    )

def _summarize(buildables):
    for buildable in buildables:
        logger.info('Built changes files from %s:\n\t%s',
                buildable,
                '\n\t'.join(sorted(buildable.changes_produced.values())),
                )

        logger.info('Build logs from %s:\n\t%s',
                buildable,
                '\n\t'.join(sorted(buildable.logs.values())),
                )

def _lintian(buildables):
    for buildable in buildables:
        # Run lintian near the end for better visibility
        for x in 'source+binary', 'binary', 'source':
            if x in buildable.merged_changes:
                subprocess.call(['lintian', '-I', '-i',
                    buildable.merged_changes[x]])

                break

def _publish(buildables, output_builds,
        reprepro_dir, default_reprepro_suite=None):
    for buildable in buildables:
        for x in 'source+binary', 'binary', 'source':
            if x in buildable.merged_changes:
                reprepro_suite = default_reprepro_suite

                if reprepro_suite is None:
                    reprepro_suite = buildable.nominal_suite

                subprocess.call(['reprepro', '-b', reprepro_dir,
                    'removesrc', str(reprepro_suite),
                    buildable.source_package])
                subprocess.call(['reprepro', '--ignore=wrongdistribution',
                    '--ignore=missingfile',
                    '-b', reprepro_dir, 'include',
                    str(reprepro_suite),
                    os.path.join(output_builds,
                        buildable.merged_changes[x])])
                break

def run(args):
    components = args.components
    output_builds = args.output_builds
    storage = args.storage
    vendor = args.vendor

    buildables = []

    for a in (args._buildables or ['.']):
        buildable = Buildable(a, vendor=vendor)
        buildable.select_suite(args.suite)
        buildables.append(buildable)

    for suite in (args.suite, args.sbuild_worker_suite):
        if suite is None:
            continue

        for ancestor in suite.hierarchy:
            if ancestor.mirror is None:
                raise ArgumentError('mirror or apt_cacher_ng must be '
                        'configured for {}'.format(ancestor))

    with VirtWorker(args.sbuild_worker.split(),
            suite=args.sbuild_worker_suite,
            ) as worker:
        default_architecture = worker.dpkg_architecture
        _sbuild(args, buildables,
                archs=args._archs,
                components=components,
                extra_repositories=args._extra_repository,
                indep=args._indep,
                output_builds=output_builds,
                rebuild_source=args._rebuild_source,
                source_only=args._source_only,
                storage=storage,
                together=args.sbuild_together,
                vendor=vendor,
                worker=worker,
                )

    _autopkgtest(args, buildables, default_architecture,
            components=components,
            extra_repositories=args._extra_repository,
            lxc_24bit_subnet=args.lxc_24bit_subnet,
            lxc_worker=args.lxc_worker,
            lxc_worker_suite=args.lxc_worker_suite,
            mirror=args.mirror,
            modes=args.autopkgtest,
            storage=storage,
            vendor=vendor,
            worker_argv=args.worker,
            worker_suite=args.worker_suite,
            )
    _summarize(buildables)
    _lintian(buildables)

    if args._reprepro_dir:
        _publish(buildables, args.output_builds, args._reprepro_dir,
                args._reprepro_suite)

    # We print these separately, right at the end, so that if you built more
    # than one thing, the last screenful of information is the really
    # important bit for testing/signing/upload
    for buildable in buildables:
        logger.info('Merged changes files from %s:\n\t%s',
                buildable,
                '\n\t'.join(buildable.merged_changes.values()),
                )
