from __future__ import annotations

import typing as typ

import subprocess as sproc
from dataclasses import dataclass

from .irqs import IRQ_TYPE
from . import tools as tl

import logging

logg = logging.getLogger(__name__)


@dataclass
class PCIDevice:
    pci_addr: str
    irq_type: IRQ_TYPE
    irq_list: list[int]
    cpu_set: set[int]
    numa_node: int

    driver: str = ''
    net_iface: str = ''
    ip_addr: str = ''

    def __repr__(self) -> str:
        s = f'PCI@{self.pci_addr}'
        if self.irq_type != IRQ_TYPE.NONE:
            s += f' - {len(self.irq_list)} IRQs ({self.irq_type.name})'
        if self.driver:
            s += f' - mod. {self.driver}'
        if self.net_iface:
            s += f' - net. {self.net_iface}/{self.ip_addr}'
        return s

    def add_driver_info(self, driver: str) -> None:
        logg.debug(
            f'PCIDevice::add_driver_info() - {self.pci_addr}, {self.driver}')
        self.driver = driver

    def add_network_iface(self, iface: str) -> None:
        self.net_iface = iface
        # Hopefully only one IP...
        self.ip_addr = sproc.run(
            f'ip addr show {self.net_iface}' +
            ' | grep "\<inet\>" | awk \'{ print $2 }\' | awk -F "/" \'{ print $1 }\'',
            shell=True,
            stdout=sproc.PIPE).stdout.decode().strip()

        logg.info(
            f'PCIDevice::add_network_iface() - {self.pci_addr}, {self.net_iface} IP {self.ip_addr}'
        )

        self.net_is_lan = self.ip_addr.split('.')[0] in ['10', '192']

    def __hash__(self) -> int:
        return self.pci_addr.__hash__()
