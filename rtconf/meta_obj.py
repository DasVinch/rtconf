from __future__ import annotations

import typing as typ

if typ.TYPE_CHECKING:
    from .kthread import KThread
    from .irqs import IRQ
    from .cset import CPUSpec

from . import tools as tl

import logging

logg = logging.getLogger(__name__)

# EDT has 1 irq, 1 kthread, 1 pcidevice. Easy.
# And possibly we have the co-referenced from the functions already.


class EDTObject:  # Could really subclass IRQ - but we'd need to promote class once we find the PCI device.

    def __init__(self,
                 *,
                 irq: IRQ | None = None,
                 kthread: KThread | None = None) -> None:

        logg.debug('EDTObject::__init__')

        if irq:
            self.irq = irq
            assert self.irq.kthread is not None
            self.kthread = self.irq.kthread
        elif kthread:
            self.kthread = kthread
            assert self.kthread._irq_obj is not None
            self.irq = self.kthread._irq_obj
        else:
            raise ValueError('Need either irq or kthread.')

        assert self.irq.pci_device is not None
        self.pci_device = self.irq.pci_device

        logg.warning(
            f'EDTObject::__init__ - bound together IRQ {self.irq.id}, kt {self.kthread.name} {self.kthread.pid}, PCI {self.pci_device.ip_addr}'
        )

    def bind_to_cset(self, cset: CPUSpec, ktprio: int | None = None) -> None:
        logg.info(
            f'EDTObject::bind_to_cset - IRQ {self.irq.id} / KT {self.kthread.pid} onto CPUs {cset.get_str()}'
        )

        assert len(cset.cpu_list) == 1

        cpu = cset.cpu_list[0]

        if not cpu in tl.NUMA_CPULIST[self.irq.best_node]:
            msg = 'EDTObj: use of favorite NUMA node required.'
            logg.critical(msg)
            raise RuntimeError(msg)

        self.irq.set_pin_to_cpu(cset.cpu_list)
        self.kthread.pin_cset(cset)

        if ktprio is not None:
            self.kthread.chrt_ff(ktprio)

        irq_cpulist = self.irq.get_pin_to_cpu()
        kt_cpulist = self.kthread.get_taskset().cpu_list

        assert len(irq_cpulist) == 1 and irq_cpulist[0] == cpu
        assert len(kt_cpulist) == 1 and kt_cpulist[0] == cpu
