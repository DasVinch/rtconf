from __future__ import annotations

from typing import TYPE_CHECKING, Set, List
if TYPE_CHECKING:
    from .pcidevices import PCIDevice
    from .cset import CPUSpec
    from .irqs import IRQ
    from .kthread import KThread

import re
import subprocess as sproc

from . import tools as tl

import logging

logg = logging.getLogger(__name__)


@tl.root_decorator
def network_hiperf_single(dev: PCIDevice) -> None:

    logg.warning(
        f'network_hiperf_single() onto dev {dev} with interface {dev.net_iface}'
    )

    assert dev.net_iface and dev.net_is_lan

    sproc.run(f'ethtool -C {dev.net_iface} rx-usecs 0', shell=True)
    sproc.run(f'ethtool -C {dev.net_iface} tx-usecs 0', shell=True)
    sproc.run(f'ethtool -A {dev.net_iface} autoneg off rx off tx off',
              shell=True)
    # Further stemming from the following line:
    # sudo ethtool -K ens9f1np1 gso off tso off gro off lro off tx off rx off
    # Used on 40G LAN and 100G P2P - this is too much load otherwise on RT packets for
    # the NIC firmware to handle.
    sproc.run(
        f'ethtool -K {dev.net_iface} gso off tso off gro off lro off tx off rx off',
        shell=True)


@tl.root_decorator
def network_generic_all() -> None:
    logg.warning(
        f'network_generic_all() - applying systemctl hiperf network tweaks.')
    from .rtlinux_configs import SYSCTL_TWEAK_LIST_NETWORK
    tl.sysctl_write_list(SYSCTL_TWEAK_LIST_NETWORK)


@tl.root_decorator
def hyperthreading_disable() -> None:
    '''
    Note: if we want to *partially* disable hyperthreading, which would be really nice.
    Things are gonna get a little more subtle. In particular we need to **carefully**
    re-enumerate the numa nodes after dropping CPUs off.

    This function detects if any hyperthreading is running and drops off all sibling CPUs.
    '''
    logg.warning(f'hyperthreading_disable()')

    pfix = '/sys/devices/system/cpu'

    sibling_enumeration_all = sproc.run(
        f'grep . {pfix}/cpu[0-9]*/topology/thread_siblings_list',
        shell=True,
        stdout=sproc.PIPE).stdout.decode().rstrip().split('\n')

    re_parse = re.compile(
        f'^{pfix}/cpu(\d+)/topology/thread_siblings_list:(\d+)(?:,(\d+))?$')

    found_comma = False
    set_toremove: Set[int] = set()

    for cpuline in sibling_enumeration_all:
        match = re_parse.findall(cpuline)[0]
        cpu = int(match[0])

        lowest_sibling = int(match[1])

        if lowest_sibling != cpu:
            set_toremove.add(cpu)

    if found_comma:
        # Send a warning to disable in BIOS.
        pass

    for cpu in set_toremove:
        logg.warning(f'hyperthreading_disable(): setting CPU {cpu} offline.')
        tl.procfs_write(f'{pfix}/cpu{cpu}/online', '0')


@tl.root_decorator
def cpu_performance_mode_enable() -> None:
    logg.warning(
        f'cpu_performance_mode_enable() - sysctl + cpupower + governor')
    from .rtlinux_configs import SYSCTL_TWEAK_LIST_CPUPERF
    tl.procfs_write_list([(file, on)
                          for (file, on, _) in SYSCTL_TWEAK_LIST_CPUPERF])

    cmd = 'cpupower -c all idle-set -d'  # disable state from deep to shallow
    for k in range(10, 0, -1):
        sproc.run(cmd.split(' ') + [str(k)])

    cmd = 'cpupower frequency-set --governor performance'
    sproc.run(cmd.split(' '))


@tl.root_decorator
def cpu_performance_mode_disable() -> None:
    logg.warning(
        f'cpu_performance_mode_disable() - sysctl + cpupower + governor')
    from .rtlinux_configs import SYSCTL_TWEAK_LIST_CPUPERF
    tl.procfs_write_list([(file, off)
                          for (file, _, off) in SYSCTL_TWEAK_LIST_CPUPERF])

    cmd = 'cpupower -c all idle-set -e'  # enable state from shallow to deep
    for k in range(1, 3):
        sproc.run(cmd.split(' ') + [str(k)])

    cmd = 'cpupower frequency-set --governor powersave'
    sproc.run(cmd.split(' '))


@tl.no_root_decorator
def hold_cpu_dma_latency() -> None:
    '''
        Require NO ROOT because we're using the user's tmux.
    '''
    logg.warning('hold_cpu_dma_latency - starting cc-setlatency 0 in tmux.')
    # Keep the tmux magic approach.
    from .. import tmux

    pane = tmux.find_or_create('cpulatency')
    tmux.kill_running(pane)
    tmux.send_keys(pane, 'cc-setlatency 0')


@tl.root_decorator
def irq_parking(irqs: List[IRQ], cpus: CPUSpec) -> None:
    # Begin by disabling IRQbalance.
    logg.warning(
        f'irq_parking() - stopping irqbalance; moving {len(irqs)} onto CPUs {cpus.get_str()}'
    )

    sproc.run(['systemctl', 'stop', 'irqbalance'])

    # Ideally we want to restart irqbalance excluding banned CPUs and relevant interrupts.
    for irq in irqs:
        # Ideally, we want a numa-aware version of this.
        irq.set_pin_to_cpu(cpus.cpu_list, numaify_subset_ok=True)


@tl.root_decorator
def irq_restart(cpus_nobalance: CPUSpec, irqs_nobalance: Set[IRQ]) -> None:

    ids = [irq.id for irq in irqs_nobalance]
    logg.warning(
        f'irq_restart() - Reconfiguring irqbalance; blacklisting CPUs {cpus_nobalance.get_str()} - protecting irqs {ids}.'
    )

    cpus_no_balancing_mask = tl.list_to_mask(cpus_nobalance.cpu_list)
    strmask = f'{cpus_no_balancing_mask:x}'
    strmask_commad = ''
    while len(strmask) > 0:
        strmask_commad = strmask[-8:] + ',' + strmask_commad
        strmask = strmask[:-8]
    strmask_commad = strmask_commad[:-1]

    with open('/etc/default/irqbalance', 'r') as f:
        lines = f.readlines()

    autogen_warn = '# WARNING - THIS FILE WRITTEN BY SCRIPT / swmain.infra.rtconf.macros'
    full_line_BANNED_CPUS = f'IRQBALANCE_BANNED_CPUS="{strmask_commad}"' + \
        autogen_warn + '\n'
    list_banirq = [f'--banirq={str(irq.id)}' for irq in irqs_nobalance]
    full_line_ARGS = f'IRQBALANCE_ARGS="{" ".join(list_banirq)}"' + \
        autogen_warn + '\n'

    for ll in range(len(lines)):
        if 'IRQBALANCE_BANNED_CPUS=' in lines[ll]:
            lines[ll] = full_line_BANNED_CPUS
        if 'IRQBALANCE_ARGS=' in lines[ll]:
            lines[ll] = full_line_ARGS

    # I'm a moron -- it's /etc/default/irqbalance on ubuntu
    # /etc/sysconfig/irqbalance on RHEL/SUSE
    with open('/etc/default/irqbalance', 'w') as f:
        f.writelines(lines)
    with open('/etc/sysconfig/irqbalance', 'w') as f:
        f.writelines(lines)

    sproc.run(['systemctl', 'start', 'irqbalance'])


@tl.root_decorator
def cset_destruction():
    '''
        Destroy all currently existing cpusets
    '''
    from .functions import rescan_cpusets
    logg.warning(f'cset_destruction() - destroying all current csets.')

    cpuset_dict = rescan_cpusets()
    for name in cpuset_dict:
        if name != '/':
            sproc.run(f'cset set -d {name}'.split(' '))


@tl.root_decorator
def cset_creation(csets: List[CPUSpec], shield_cpus: CPUSpec) -> None:

    logg.warning(
        f'cset_creation() - Initializing {len(csets)} - shielded CPUs: {shield_cpus.get_str()}.'
    )

    # There's a glitch on AMD, so first let's make a "cset shield"
    sproc.run(
        f'cset shield -c {tl.list_to_range_notation(shield_cpus.cpu_list)}'.
        split(' '))
    # then destroy the shielded set - but some other tweaks happened (?)
    sproc.run('cset set -d user'.split(' '))
    # Also enable all memory banks for /system
    # ASSUME shield-cpus has all memories enabled
    assert shield_cpus.mem_list is not None
    mem_range = tl.list_to_range_notation(shield_cpus.mem_list)
    sproc.run(f'cset set -m {mem_range} system'.split(' '))

    # Now create the custom csets.
    for cset in csets:
        cset.create()

    # Now re-force the migration (shield should have done some of it.)
    sproc.run('cset proc -m -k --force --threads -f root -t system'.split())
    sproc.run('cset proc -k --force root -t system'.split())


def irq_summary(irqs: List[IRQ]) -> None:
    for irq in irqs:
        if not irq.was_pinned_successfully_once:
            if irq.pci_device is not None:
                s = f'(dev {irq.pci_device.pci_addr}, {irq.pci_device.driver})'
            else:
                s = 'undefined irq PCI data.'
            logg.debug(f'irq_summary: Untouched IRQ {irq.id} {s}')


def kthread_summary(kts: List[KThread]) -> None:
    from .kthread import KThreadTypeEnum as KTTE
    for kt in kts:
        if not kt.was_cset_successfully_once:
            # Some are valid to not be moved.
            ok_nomove = (kt.kthread_type in [
                KTTE.RCUC, KTTE.CPUHP, KTTE.KSOFTIRQD, KTTE.IDLE_INJECT,
                KTTE.MIGRATION, KTTE.IDLE_INJECT, KTTE.IRQ_WORK
            ] or (kt.kthread_type == KTTE.KWORKER
                  and 'mm_percpu_wq' in kt._comm)
                         or (kt.kthread_type == KTTE.KWORKER
                             and 'events_highpri' in kt._comm))
            if not ok_nomove:
                ts = kt.get_taskset()
                logg.debug(
                    f'kt_summary: Untouched KT {kt.pid} {kt.name} | on CPUs {ts.get_str()}'
                )


@tl.root_decorator
def test_root_call() -> None:
    logg.warning('test_root_call().')
    pass


@tl.no_root_decorator
def test_non_root_call() -> None:
    logg.warning('test_non_root_call().')
    pass
