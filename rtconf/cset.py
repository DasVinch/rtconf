'''
    It's honetly simpler to bind to process calls for commonly used sets
    Rather than bother to interface cleanly with the cset python API.
'''

from typing import List, Optional as Op

from . import tools as tl

import subprocess as sproc

import logging

logg = logging.getLogger(__name__)


class CPUSpec:

    def __init__(self,
                 name: str,
                 *,
                 str_spec: Op[str] = None,
                 cpu_list: Op[List[int]] = None,
                 mem_list: Op[List[int]] = None,
                 mask: Op[int] = None,
                 no_irqbalance: bool = False) -> None:

        logg.debug('CPUSpec::__init__')

        assert (str_spec is None) + (cpu_list is None) + (mask is None) == 2

        self.name = name

        if str_spec is not None:  # '' is valid
            cpu_list = tl.range_to_list(str_spec)
        elif mask is not None:
            cpu_list = tl.mask_to_list(mask)
        else:
            assert cpu_list is not None

        self.cpu_list = cpu_list
        self.cpu_list.sort()
        self.mask = tl.list_to_mask(self.cpu_list)

        self.mem_list = mem_list

        self.no_irqbalance = no_irqbalance  # Use to flag disabling from irqbalance.

    def __repr__(self) -> str:
        return f'({self.name}, {tl.list_to_range_notation(self.cpu_list)})'

    def get_str(self) -> str:
        return tl.list_to_range_notation(self.cpu_list)

    @tl.root_decorator
    def create(self) -> None:
        cpu_str = self.get_str()
        logg.info(f'CPUSpec::create ({self.name}, {cpu_str})')
        cmd = f'cset set --cpu {cpu_str}'
        if self.mem_list is not None:
            cmd += f' -m {tl.list_to_range_notation(self.mem_list)}'
        cmd += f' --set {self.name}'

        r = sproc.run(cmd.split(' ')).returncode
        if r != 0:
            logg.error(f'CPUSpec::create failed - cset return {r}')
