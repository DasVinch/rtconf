'''
    Kernel analysis stuff.
'''
from __future__ import annotations

import typing as typ

import os
import glob
import time
import re

import subprocess as sproc

from . import tools as tl
from .irqs import IRQ, IRQ_TYPE
from .pcidevices import PCIDevice
from .cset import CPUSpec
from .kthread import KThread, KThreadTypeEnum
from .meta_obj import EDTObject  # FIXME rename this is really just a PCI + KT + IRQ struct

import numpy as np

from sortedcontainers import SortedDict

import logging

logg = logging.getLogger(__name__)


def check_command(command: str, expect_retcode: int | None = None) -> None:
    '''
    Check if a command is available in the system.
    Possible, run that command and check the retcode is expected
    '''

    logg.debug(f'check_command: {command}')

    from shutil import which

    ok = which(command) is not None
    if ok and expect_retcode is not None:
        ok = ok and (sproc.run(command, stdout=sproc.PIPE,
                               stderr=sproc.PIPE).returncode == expect_retcode)

    if not ok:
        logg.critical(f'check_command: {command} failed.')
        raise AssertionError(
            f'Program {command} not installed / not working properly.')


def update_from_proc_interrupts(irq_list: list[IRQ]) -> None:
    '''
        Stolen from the /proc/interrupts parser of Redhat's insight package
    '''

    time_now = time.time()
    content = tl.procfs_read('/proc/interrupts')

    logg.debug(f'update_from_proc_interrupts')

    try:
        cpu_names = content[0].split()
    except:
        msg = "Invalid first line of content for /proc/interrupts"
        logg.critical(msg)
        raise AssertionError(msg)

    if len(cpu_names) < 1 or not cpu_names[0].startswith("CPU"):
        msg = "Unable to determine number of CPUs in /proc/interrupts"
        logg.critical(msg)
        raise AssertionError(
            "Unable to determine number of CPUs in /proc/interrupts")

    data = SortedDict()

    for line in content[1:]:
        parts = line.split(None, len(cpu_names) + 1)

        irq_name = parts[0].replace(":", "")
        one_int: dict[str, typ.Any] = {}
        one_int['num_cpus'] = len(cpu_names)
        counts = []
        if len(parts) == len(cpu_names) + 2:
            one_int['type_device'] = parts[-1]
            for part, cpu in zip(parts[1:-1], cpu_names):
                counts.append(int(part))
        else:
            for part, cpu in zip(parts[1:], cpu_names):
                counts.append(int(part))
        one_int['counts'] = np.asarray(counts)

        data[irq_name] = one_int

    if len(data) < 1:
        msg = "No information in /proc/interrupts"
        logg.critical(msg)
        raise AssertionError(msg)

    for irq in irq_list:
        if str(irq.id) in data:
            irq.update_counts(time_now, data[str(irq.id)]['counts'])


def init_irq_objects() -> list[IRQ]:
    irq_fold = '/proc/irq'

    irq_names = [
        f.split('/')[-1] for f in glob.glob(irq_fold + '/*')
        if os.path.isdir(f)
    ]

    irq_objs = [IRQ(int(name)) for name in irq_names]

    logg.info(f'init_irq_objects: found {len(irq_objs)} /proc/irq items.')
    return irq_objs


def init_kthread_objects() -> list[KThread]:

    kthread_raw_list = sproc.run(
        ['ps', '--ppid', '2', '-p', '2', '-o', 'pid,cls,cmd'],
        stdout=sproc.PIPE).stdout.decode().split('\n')[1:-1]
    # [1:-1]: Remove title and empty line at end.
    # cmd must be last to avoid truncation

    kthread_list: list[KThread] = []

    ps_regex = re.compile(' *(\d+) *([A-Z]+) *(\[.*\])')

    for kthread_raw in kthread_raw_list:
        # Use a regex for parsing the output of ps
        p_str, cls, name = ps_regex.findall(kthread_raw)[0]
        kthread_list.append(KThread(pid=int(p_str), name=name, sched_cls=cls))

    for kt in kthread_list:
        kt.refresh_contents()

    logg.info(
        f'init_kthread_objects: found {len(kthread_list)} /proc/irq items.')
    return kthread_list


def filter_network_kthreads(all_kthreads: list[KThread],
                            iface: str | None) -> list[KThread]:
    # TODO
    return []


def identify_fg_objs(irq_list: list[IRQ], driver: str) -> list[EDTObject]:
    # Identify the EDT irqs.
    fg_objs = [
        EDTObject(irq=irq) for irq in irq_list
        if (irq.pci_device is not None and irq.pci_device.driver == driver)
    ]
    fg_objs.sort(key=lambda e: e.pci_device.pci_addr
                 )  # PCI addr order == pdv obj order.

    return fg_objs


def identify_net_objs(irq_list: list[IRQ], iface: str) -> list[EDTObject]:
    net_objs = [
        EDTObject(irq=irq) for irq in irq_list
        if (irq.pci_device is not None and irq.pci_device.net_iface == iface)
    ]
    return net_objs


def init_pci_objects() -> list[PCIDevice]:
    pci_fold = '/sys/bus/pci/devices'

    devices = glob.glob(pci_fold + '/*')
    dev_objs = []

    # For mapping modules to PCI devices
    lsmod = tl.parse_lsmod()
    procpci = tl.procfs_read('/proc/bus/pci/devices')
    procpci_dict = {p.split('\t')[0]: p.split('\t')[-1] for p in procpci}

    # Special PCI objects that play stupid...
    procpci_dict.update({k: 'edt' for k in tl.parse_lspci_for_edt_boards()})
    procpci_dict.update(
        {k: 'dcfi_nsl_module'
         for k in tl.parse_lspci_for_fpdp_boards()})
    # this might get really old, really quickly.

    # For mapping network interfaces to PCI devices
    raw_netpci = sproc.run(
        'grep -H PCI_SLOT_NAME /sys/class/net/*/device/uevent',
        shell=True,
        stdout=sproc.PIPE).stdout.decode().rstrip().split('\n')
    re_netpci = re.compile(
        '^/sys/class/net/(.*)/device/uevent:PCI_SLOT_NAME=(.*)$')
    netpci_dict: dict[str, str] = {}
    for iface_line in raw_netpci:
        _match = re_netpci.findall(iface_line)[0]
        netpci_dict[_match[1]] = _match[0]

    netpci_dict_shortaddr = {s[5:]: netpci_dict[s] for s in netpci_dict}
    logg.warning(f'PCI/network mappings found: {netpci_dict_shortaddr}')

    pcidev_switch_blacklist = tl.parse_lspci_for_pci_switches()

    for fullpath_addr in devices:
        pci_addr = fullpath_addr.split('/')[-1]  # 0000:XX:YY.Z
        addr_4ch = pci_addr.split('.')[0].replace(':', '')[4:]  # XXYY

        if addr_4ch in pcidev_switch_blacklist:
            # Bypass PCI switches.
            # They're a problem because they share the interrupt with
            # the leaf PCI devices.
            continue

        if os.path.isdir(f'{fullpath_addr}/msi_irqs'):
            irq_type = IRQ_TYPE.MSI
            irq_list = [
                int(x) for x in os.listdir(f'{fullpath_addr}/msi_irqs')
            ]
        elif os.path.isfile(f'{fullpath_addr}/irq'):
            irq_type = IRQ_TYPE.LEGACY
            irq_list = [int(tl.procfs_read(f'{fullpath_addr}/irq')[0])]
        else:
            irq_type = IRQ_TYPE.NONE
            irq_list = []

        cpus = set(
            tl.range_to_list(
                tl.procfs_read(f'{fullpath_addr}/local_cpulist')[0]))

        if cpus == tl.ALL_CPUS:
            numa = -1
        else:
            numa = tl.NUMA_CPULIST.index(cpus)

        dev = PCIDevice(pci_addr=pci_addr,
                        irq_type=irq_type,
                        irq_list=irq_list,
                        cpu_set=cpus,
                        numa_node=numa)
        dev_objs.append(dev)

        # Now map kernel module to PCI device.
        module = procpci_dict.get(addr_4ch, '')
        if not module in lsmod:
            module = ''

        dev.add_driver_info(module)

        # Network iface?
        if pci_addr in netpci_dict:
            dev.add_network_iface(netpci_dict[pci_addr])

    logg.info(f'init_pci_objects: found {len(dev_objs)} PCIe items.')
    devs_with_named_driver: set[PCIDevice] = {d for d in dev_objs if d.driver}
    drivers_with_pci_obj: set[str] = {d.driver for d in devs_with_named_driver}
    logg.info(f'init_pci_objects: found {len(devs_with_named_driver)} '
              f'PCIe items with nominative drivers {drivers_with_pci_obj}')
    logg.info(f'init_pci_objects: found {len(netpci_dict)} network interfaces')

    return dev_objs


def match_irq_and_pci(irqs: list[IRQ], devs: list[PCIDevice]) -> None:
    reverse_lookup: dict[int, PCIDevice] = {}
    logg.debug('match_irq_and_pci()')

    # New problem - we may have multiple devices reclaiming the same irq
    # This happens with fpdp/nsl... if certain slots the legacy IRQ is claimed
    # by both the device itself and an upstream PCI switch.
    # Just keep the highest PCI adress?
    # But what in the case of master/aux devices (e.g nvidia video XX.0 and sound at XX.1)
    for dev in devs:
        for pci_irq in dev.irq_list:
            if ((not pci_irq in reverse_lookup) or
                (reverse_lookup[pci_irq].pci_addr <
                 dev.pci_addr)):  # Hotfixin' in case of dual IRQ-claiming
                reverse_lookup[pci_irq] = dev

    for irq in irqs:
        if irq.id in reverse_lookup:
            irq.register_pci_device(reverse_lookup[irq.id])

    irq_has_pcidev = {irq for irq in irqs if irq.pci_device is not None}
    logg.info(
        f'match_irq_and_pci: Matched {len(irq_has_pcidev)} IRQs to PCI devices.'
    )


def match_kthread_and_irq(irqs: list[IRQ], kthreads: list[KThread]) -> None:
    # Does each IRQ have a kthread?
    # Does each IRQ-type kthread have an IRQ?
    logg.debug('match_kthread_and_irq()')

    # Reverse lookup kthreads by irq number.
    reverse_lookup: dict[int, KThread] = {}
    for kthread in kthreads:
        #if kthread.kthread_type == KThreadTypeEnum.IRQ:
        if kthread._irq_number is not None:
            reverse_lookup[kthread._irq_number] = kthread

    for irq in irqs:
        if irq.id in reverse_lookup:
            irq.register_kthread(reverse_lookup[irq.id])
            reverse_lookup[irq.id].register_interrupt(irq)

    irq_has_kt = {irq for irq in irqs if irq.kthread is not None}
    logg.info(
        f'match_irq_and_pci: Matched {len(irq_has_kt)} IRQ/KThread pairs.')


def rescan_cpusets() -> dict[str, CPUSpec]:
    ''' Either /usr/bin/python, or pip install cpuset-py3 in user distro '''
    logg.debug('rescan_cpusets()')

    from cpuset import cset

    _ = cset.CpuSet()
    sets: dict[str, cset.CpuSet] = cset.CpuSet.sets

    my_sets = {
        name: CPUSpec(sets[name].name, str_spec=sets[name].getcpus())
        for name in sets
    }
    logg.info(f'rescan_cpusets: found {len(my_sets)} - {my_sets}')
    return my_sets


if __name__ == "__main__":
    from rtconf import functions
    irqs = functions.init_irq_objects()
    devs = functions.init_pci_objects()
    kthreads = functions.init_kthread_objects()

    functions.match_irq_and_pci(irqs, devs)
    functions.match_kthread_and_irq(irqs, kthreads)

    import time

    mlxirqs = [
        irq for irq in irqs
        if irq.pci_device and irq.pci_device.driver == 'mlx5_core'
    ]

    for i in range(0):
        time.sleep(1.0)
        update_from_proc_interrupts(mlxirqs)
        mlxirqs.sort(key=lambda irq: sum(irq._counts_hz), reverse=True)

        print(f'----------- {time.time() % 1000}')
        for irq in mlxirqs:
            irq.refresh_contents()
        fastirqs = [i for i in mlxirqs if sum(i._counts_hz) > 1000]
        fastirqs.sort(key=lambda x: x.id)
        for irq in fastirqs:
            print(irq)
            print(f'{sum(irq._counts_hz):.2f} Hz.')
