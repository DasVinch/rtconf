from __future__ import annotations

import typing as typ
if typ.TYPE_CHECKING:
    from .pcidevices import PCIDevice
    from .kthread import KThread

import logging

logg = logging.getLogger(__name__)

import numpy as np

from . import tools as tl

from enum import IntEnum


class IRQ_TYPE(IntEnum):
    NONE = 0
    LEGACY = 1
    MSI = 2


class IRQ:

    def __init__(self, id: int) -> None:
        logg.debug(f'IRQ::__init__ {id}')

        self.id: int = id
        self.procfs_folder: str = f'/proc/irq/{self.id}'

        # I don't do affinity_hint since I expect irqbalance to be off on a RT machine.

        self._smp_affinity: int = 0x0
        self._smp_affinity_list: list[int] = []

        self._eff_affinity: int = 0x0
        self._eff_affinity_list: list[int] = []

        self.best_node: int = -2
        self.pci_device: PCIDevice | None = None

        self.kthread: KThread | None = None

        self._count: int = 0
        self._unhandled: int = 0
        self._last_unhandled_ms: int = 0

        self._counts: np.ndarray[typ.Any, np.dtype[np.int64]] = np.zeros(
            tl.CPU_COUNT, np.int64)
        self._counts_time: float = 0
        self._counts_hz: np.ndarray[typ.Any, np.dtype[np.float64]] = np.zeros(
            tl.CPU_COUNT, np.float64)

        self.was_pinned_successfully_once = False

        self.refresh_contents()

    def __repr__(self) -> str:
        s = (
            f'IRQ {self.id:3d} - Allowed {tl.list_to_range_notation(self._smp_affinity_list)}; '
            f'current {tl.list_to_range_notation(self._eff_affinity_list)}')
        if self.pci_device:
            s += f'- PCI dev {self.pci_device.pci_addr} (drv {self.pci_device.driver}) - NUMA {self.best_node}.'

        return s

    def update_counts(self, time_now: float, counts: np.ndarray) -> None:
        logg.debug('IRQ::update_counts()')

        assert len(counts) == tl.CPU_COUNT

        self._counts_hz = (counts - self._counts) / \
                           (time_now - self._counts_time)
        self._counts_time = time_now
        self._counts = counts

    def refresh_contents(self) -> None:
        logg.debug('IRQ::refresh_contents()')
        self._smp_affinity = tl.maskstr_to_int(
            self.procfs_read('smp_affinity')[0])
        self._smp_affinity_list = tl.mask_to_list(self._smp_affinity)
        self._eff_affinity = tl.maskstr_to_int(
            self.procfs_read('effective_affinity')[0])
        self._eff_affinity_list = tl.mask_to_list(self._eff_affinity)

        spurious = self.procfs_read('spurious')
        self._count = int(spurious[0].split()[1])
        self._unhandled = int(spurious[1].split()[1])
        self._last_unhandled_ms = int(spurious[2].split()[1])

    def register_pci_device(self, dev: PCIDevice) -> None:
        logg.info(f'IRQ::register_pci_device() {dev} onto IRQ {self}')
        self.pci_device = dev
        self.best_node = dev.numa_node

    def register_kthread(self, kthread: KThread) -> None:
        logg.info(f'IRQ::register_kthread() {kthread} onto IRQ {self}')
        self.kthread = kthread

    @tl.root_decorator
    def procfs_write(self, file: str, content: str) -> None:
        tl.procfs_write(f'{self.procfs_folder}/{file}', content)

    def procfs_read(self, file: str) -> list[str]:
        return tl.procfs_read(f'{self.procfs_folder}/{file}')

    def get_pin_to_cpu(self) -> list[int]:
        self.refresh_contents()
        logg.info(
            f'IRQ::get_pin_to_cpu(): IRQ {self.id} bound to {tl.list_to_range_notation(self._smp_affinity_list)}'
        )
        return self._smp_affinity_list

    @tl.root_decorator
    def set_pin_to_cpu(self,
                       cpu_list: list[int],
                       numaify_subset_ok: bool = False) -> list[int]:

        logg.info(
            f'IRQ::set_pin_to_cpu(): IRQ {self.id} onto to {tl.list_to_range_notation(cpu_list)}'
        )

        assert len(cpu_list) > 0
        cpu_list_effective = cpu_list

        if self.best_node >= 0:  # Has a preferred NUMA node
            superset_bool = set(
                tl.NUMA_CPULIST[self.best_node]).issuperset(cpu_list)
            if not superset_bool:
                if numaify_subset_ok:
                    # intersect cpu_list with the preferred node.
                    cpu_list_effective = [
                        c for c in cpu_list
                        if c in tl.NUMA_CPULIST[self.best_node]
                    ]
                else:
                    # log an error. Still try to pin tho
                    logg.error(
                        f'Pinning IRQ {self.id} to CPUs {tl.list_to_range_notation(cpu_list)}, not on NUMA node {self.best_node}'
                    )

        try:
            self.procfs_write('smp_affinity_list',
                              tl.list_to_range_notation(cpu_list_effective))
        except OSError:
            logg.debug(
                f'IRQ::set_pin_to_cpu OSError - irq: {self.id} - '
                f'SMP current: {tl.list_to_range_notation(self._smp_affinity_list)} - '
                f'SMP tried: {tl.list_to_range_notation(cpu_list)}')

        pinned = self.get_pin_to_cpu()
        if set(pinned) == set(cpu_list_effective):
            self.was_pinned_successfully_once = True

        return pinned
