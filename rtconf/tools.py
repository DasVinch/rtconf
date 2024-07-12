import os
import subprocess as sproc

from enum import IntEnum

from typing import List, Callable, Tuple, Set, Any, Union, Iterable, TypeVar
from typing_extensions import ParamSpec  # Will be in typing in 3.10

import logging

logg = logging.getLogger(__name__)


class ProcfsWriteError(Exception):
    pass


P = ParamSpec("P")
R = TypeVar("R")


def root_decorator(func: Callable[P, R]) -> Callable[P, R]:

    def decorated_func(*args: P.args, **kwargs: P.kwargs) -> R:
        if os.getuid() != 0:
            raise PermissionError('Must be root.')
        return func(*args, **kwargs)

    return decorated_func


def no_root_decorator(func: Callable[P, R]) -> Callable[P, R]:

    def decorated_func(*args: P.args, **kwargs: P.kwargs) -> R:
        if os.getuid() == 0:
            raise PermissionError('Must not be root.')
        return func(*args, **kwargs)

    return decorated_func


def range_to_list(range_str: str) -> List[int]:

    if len(range_str) == 0:
        return []

    int_list = []
    for token in range_str.split(','):
        if '-' in token:
            l, h = [int(t) for t in token.split('-')]
            assert l <= h

            int_list += list(range(l, h + 1))
        else:
            int_list += [int(token)]

    return int_list


def list_to_range_notation(cpu_list: List[int]) -> str:

    # Assume the list is sorted... or redo it.
    cpu_list.sort()

    pending: List[int] = []

    s = ''

    # Adding [-1] in iterator avoid having to finalize the last range
    # after the loop
    for c in cpu_list + [-1]:
        if len(pending) == 0:
            pending = [c]
            continue

        if c == pending[-1] + 1:
            pending.append(c)
            continue

        if len(pending) == 1:
            s += f',{pending[0]}'
        else:  # >= 2
            s += f',{pending[0]}-{pending[-1]}'
        pending = [c]

    # To confirm
    assert pending == [-1]

    # Pop the initial comma
    return s[1:]


def maskstr_to_int(maskstr: str) -> int:
    # Solve the issue of comma-separated hexlists when more than 8-chars.
    return int(maskstr.replace(',', ''), 16)


def mask_to_list(mask: int) -> List[int]:
    assert mask >= 0

    int_list = []
    cc = 0
    while mask > 0:
        if mask & 0x1:
            int_list.append(cc)
        cc += 1
        mask >>= 1

    return int_list


def list_to_mask(cpu_list: Iterable[int]) -> int:
    mask = 0x0
    for cc in cpu_list:
        mask |= 1 << cc

    return mask


@root_decorator
def procfs_write(file: str, content: str) -> None:
    with open(file, 'w') as f:
        ret = f.write(content)
    if ret <= 0:
        raise ProcfsWriteError(
            f'Error writing to procfs file: {file} - value {content}')


@root_decorator
def procfs_write_list(config: List[Tuple[str, Union[str, int]]]) -> None:
    for file, value in config:
        procfs_write(file, str(value))


def procfs_read(file: str) -> List[str]:
    with open(file, 'r') as f:
        content = f.readlines()
    return [c.rstrip() for c in content]


@root_decorator
def sysctl_write_list(config: List[Tuple[str, Union[str, int]]]) -> None:
    for sysctl_key, value in config:
        sysctl_write(sysctl_key, str(value))


@root_decorator
def sysctl_write(sysctl_key: str, contents: str) -> None:
    sysctl_file = '/proc/sys/' + sysctl_key.replace('.', '/')
    try:
        procfs_write(sysctl_file, contents)
    except FileNotFoundError:
        logg.error(
            f'sysctl_write: key {sysctl_key} (for value {contents}) does not exist'
        )


def sysctl_read(sysctl_key: str) -> str:
    sysctl_file = '/proc/sys/' + sysctl_key.replace('.', '/')
    read = ''
    try:
        read = procfs_read(sysctl_file)[0]
    except FileNotFoundError:
        logg.error(f'sysctl_read: key {sysctl_key} does not exist')

    return read


def parse_numa_info() -> Tuple[int, List[Set[int]]]:

    p = sproc.run('lscpu | grep NUMA', shell=True, stdout=sproc.PIPE)
    res = p.stdout.decode().split('\n')[:-1]

    nodes = int(res[0].split(':')[1])
    sets_per_node = []
    for nn in range(nodes):
        cpu_range = res[nn + 1].split(':')[1].strip()
        sets_per_node += [set(range_to_list(cpu_range))]

    return nodes, sets_per_node


def parse_lsmod() -> List[str]:
    p = sproc.run('lsmod', shell=True, stdout=sproc.PIPE)
    res = p.stdout.decode().split('\n')[:-1]
    modules = [l.split()[0]
               for l in res[1:]]  # Remove title line, first column.

    return modules


def parse_lspci_for_edt_boards(format_colons: bool = False) -> List[str]:
    p = sproc.run(
        'lspci | grep "Engineering Design Team, Inc." | awk \'{print $1}\'',
        shell=True,
        stdout=sproc.PIPE)

    # Contains adresses in 'XX:XX.X' format
    res = p.stdout.decode().split('\n')[:-1]

    if format_colons:
        # 0000:XX:YY.Z
        return ['0000:' + r for r in res]
    else:
        # XXYY
        return [r.split('.')[0].replace(':', '') for r in res]


def parse_lspci_for_fpdp_boards(format_colons: bool = False) -> List[str]:
    p = sproc.run(
        'lspci | grep "Systran Corp Device 464d" | awk \'{print $1}\'',
        shell=True,
        stdout=sproc.PIPE)

    # Contains adresses in 'XX:XX.X' format
    res = p.stdout.decode().split('\n')[:-1]

    if format_colons:
        # 0000:XX:YY.Z
        return ['0000:' + r for r in res]
    else:
        # XXYY
        return [r.split('.')[0].replace(':', '') for r in res]


def parse_lspci_for_pci_switches(format_colons: bool = False) -> List[str]:
    p = sproc.run('lspci | grep "PCI bridge:" | awk \'{print $1}\'',
                  shell=True,
                  stdout=sproc.PIPE)

    # Contains adresses in 'XX:XX.X' format
    res = p.stdout.decode().split('\n')[:-1]

    if format_colons:
        # 0000:XX:YY.Z
        return ['0000:' + r for r in res]
    else:
        # XXYY
        return [r.split('.')[0].replace(':', '') for r in res]


@root_decorator
def cset_proc_call(cmd_args: str) -> None:
    logg.info(
        f'cset_proc_call() - calling cset proc into the python cpuset API with args [{cmd_args}]'
    )
    import sys
    import cpuset.commands.proc as cpusetproc
    from optparse import OptionParser

    usage = cpusetproc.usage.split('\n')[0].strip()
    parser = OptionParser(usage=usage, option_list=cpusetproc.options)

    sys.argv = ['cset proc'] + cmd_args.split(' ')
    options, args = parser.parse_args()

    cpusetproc.func(parser, options, args)


# Some system constants to get on import.
CPU_COUNT: int = os.cpu_count()  # type: ignore
ALL_CPUS = set(range(CPU_COUNT))
NUMA_COUNT, NUMA_CPULIST = parse_numa_info()
MEMORY_COUNT: int = NUMA_COUNT

logg.warning(f'CPU count: {CPU_COUNT}')
logg.warning(f'All CPUs: {ALL_CPUS}')
logg.warning(f'NUMA count: {NUMA_COUNT}')
for ii in range(NUMA_COUNT):
    logg.warning(f'NUMA domain {ii}: CPUs {NUMA_CPULIST[ii]}')
