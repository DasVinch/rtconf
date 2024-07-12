'''
    Usage:
        systemconfig.py [--init] [--forkcheck]

    Options:
        --init          Init objects but do nothing. Useful to combine with interactive debugging.
        --forkcheck     Perform subprocess into root, but do nothing.

'''
# HOWTO: must install swmain into root's pip.

import os

import subprocess as sproc
import logging

SYNC_FORK_FILE = '/tmp/systemconfig_launched'

if __name__ == '__main__':

    logg = logging.getLogger(__name__)

    from docopt import docopt
    # Customize configuration?
    args = docopt(__doc__)
    ONLY_INIT = args['--init']
    FORK_CHECK_DO_NOTHING = args['--forkcheck']

    from rtconf import rtlinux_configs, functions, macros
    cfg = rtlinux_configs.find_right_config()

    # =========================
    # Initialization of objects
    # =========================
    irqs = functions.init_irq_objects()
    devs = functions.init_pci_objects()
    kthreads = functions.init_kthread_objects(
    )  # TODO: sometimes a kthread may have died between finding and reading it's files.

    functions.match_irq_and_pci(irqs, devs)
    functions.match_kthread_and_irq(irqs, kthreads)

    # cpupower retcode is 2 if compiled for wrong kernel.
    functions.check_command('cpupower', 1)
    functions.check_command('cset')

    # We need to FORK to run some stuff as root.
    # And some other stuff as not root.
    # This assume the key packages are available both
    # In the USER python distro and the SYSTEM python distro.

    we_are_root = os.getuid() == 0

    if ONLY_INIT:
        # In interactive mode (python -i), exit(0) raises a SystemExit(0)
        # But that doesn't work in SOME ipythons

        irqs_by_id = {irq.id: irq for irq in irqs}
        kt_by_pid = {kt.pid: kt for kt in kthreads}
        kt_by_name = {kt.name for kt in kthreads}

        pass  # we just want to get to the end of the file... useful for ipython -i -m debugging

    else:

        if we_are_root:  # We are root.
            os.chdir(
                '/root'
            )  # Anywhere expect where this source is. DANGEROUS to run the code without having it pip installed.

            if not os.path.isfile(SYNC_FORK_FILE):
                logg.critical('Cannot run root portion of systemconfig.py')
                raise AssertionError(
                    'Cannot run root portion of systemconfig.py')

            if FORK_CHECK_DO_NOTHING:
                print("COMPLETING FORKCHECK")
                logg.critical('Completing --forkcheck: success.')
                exit(0)

            if cfg.TEST:
                macros.test_root_call()

            if cfg.HYPERTHREADING_SOFTDISABLE:
                macros.hyperthreading_disable()

            if cfg.NETWORK_GENERIC:
                macros.network_generic_all()

            if cfg.NETWORK_LANS:
                for pcidev in devs:
                    if pcidev.net_iface and pcidev.net_is_lan:
                        macros.network_hiperf_single(pcidev)

            if cfg.CPUSETS:
                macros.cset_destruction()
                macros.cset_creation(cfg.my_cpusets, cfg.all_reserved_cpus)

            if cfg.IRQ_PARKING:
                macros.irq_parking(irqs, cfg.all_system_cpus)  # ARGH!!!!!!

            if cfg.CUSTOM_IRQ_RULES:
                cfg.irq_kthread_special_rules(irqs, kthreads)
                # Sometimes a kthread needs a nudge...
                cfg.irq_kthread_special_rules(irqs, kthreads)

                macros.irq_summary(irqs)
                macros.kthread_summary(kthreads)

            if cfg.RESTART_IRQBALANCE:
                # Restart irqbalance after applying the custom rules
                assert cfg.cpus_no_balancing is not None
                macros.irq_restart(cfg.cpus_no_balancing, cfg.irqs_nobalancing)

            if cfg.PERFORMANCE:
                macros.cpu_performance_mode_enable()
                #TODO
                pass  # PERFORMANCE_DISABLE?

            # PERF (+ GPU)

            exit(0)

        else:  # We are not root - this is executed first but calls the first block

            functions.check_command('tmux')
            # functions.check_command('cc-setlatency') skipped in standalone mode.

            if cfg.TEST:
                macros.test_non_root_call()

            with open(SYNC_FORK_FILE, 'w') as fp:
                pass
            # Run the if root block as root.
            # Pass the logfile destination to root (since it's derived from $HOME)
            cmd_array = [
                'sudo',
                #f'LOG_PATH={LOG_PATH}',
                'python3',
                '-m',
                'rtconf.systemconfig'
            ]
            if FORK_CHECK_DO_NOTHING:
                cmd_array += ['--forkcheck']
            root_subp = sproc.run(cmd_array)

            os.remove(SYNC_FORK_FILE)

            if root_subp.returncode != 0:
                logg.critical('Root portion of systemconfig.py went wrong.')
                print('''
                ---------- ERROR ----------------
                cc-systemconfig run-as-root
                configuration script errored out!
                ---------------------------------
                ''')
                import time
                time.sleep(5.0)

            if cfg.DMA_LATENCY:
                macros.hold_cpu_dma_latency()
