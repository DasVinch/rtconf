from __future__ import annotations

import typing as typ
if typ.TYPE_CHECKING:
    from .irqs import IRQ

from .cset import CPUSpec
from . import tools as tl

import os
import logging as logg
import time
import subprocess as sproc

from enum import Enum

import logging

logg = logging.getLogger(__name__)


class KThreadTypeEnum(Enum):
    # General stuff - but detailing avoids the _missing_ warning.
    KWORKER = 'kworker'
    KSOFTIRQD = 'ksoftirqd'
    MIGRATION = 'migration'
    IRQ_WORK = 'irq_work'
    IDLE_INJECT = 'idle_inject'
    CPUHP = 'cpuhp'
    PR = 'pr'

    NVIDIA_MODESET = 'nvidia-modeset'
    JBD2 = 'jbd2'

    # The ones we really care about
    IRQ = 'irq'
    RCUB = 'rcub'
    RCUC = 'rcuc'
    RCUOG = 'rcuog'
    RCUOP = 'rcuop'

    OTHER = 'other'
    # TODO A number of [mlx5] and [ib] worker threads fall under this category
    # TODO as well as [nvidia] and [nv_queue] and [UVM GPUX ...] gpu stuff.

    @classmethod
    def _missing_(cls: type, value: typ.Any) -> KThreadTypeEnum:
        logg.warning(f'KThreadTypeEnum::_missing_ {value}')
        return KThreadTypeEnum.OTHER


class KSchedTypeEnum(Enum):
    FIFO = 'FF'
    OTH = 'TS'
    UNKNOWN = 'UNKNOWN'

    @classmethod
    def _missing_(cls: type, value: typ.Any) -> KSchedTypeEnum:
        logg.warning(f'KSchedTypeEnum::_missing_ {value}')
        return KSchedTypeEnum.UNKNOWN


class KThread:  # Actually any process...

    def __init__(self, *, pid: int, name: str, sched_cls: str) -> None:
        logg.debug(f'KThread::__init__ {pid}, {name}')

        self.pid = pid
        self.name = name

        self._alive: bool = True
        self.alive()  # Actually check if alive

        self.sched_cls = KSchedTypeEnum(sched_cls)

        self.kthread_type = KThreadTypeEnum.OTHER
        slashsplit = self.name[1:-1].split(
            '/')  # remove [] around kthread name

        if '/' in self.name:
            self.kthread_type = KThreadTypeEnum(slashsplit[0])

        # Now special behaviors:
        self._irq_number: int | None = None
        self._irq_obj: IRQ | None = None

        self._is_rcu: bool = False
        self._rcuc_cpu: int | None = None

        # Not KThreadTypeEnum.OTHER implies len(slashsplit) > 1
        if self.kthread_type == KThreadTypeEnum.IRQ:
            assert len(slashsplit) > 1
            self._irq_number = int(slashsplit[1].split('-')[0])

        elif self.kthread_type in [
                KThreadTypeEnum.RCUC, KThreadTypeEnum.RCUOG,
                KThreadTypeEnum.RCUB, KThreadTypeEnum.RCUOP
        ]:
            assert len(slashsplit) > 1
            self._is_rcu = True
            self._rcuc_cpu = int(slashsplit[1])

        self.was_cset_successfully_once = False

        self._runtime, self._runtime_incr = 0.0, 0.0
        self._migrations, self._migrations_incr = 0, 0
        self._nr_sw, self._nr_sw_incr = 0, 0
        self._nr_sw_vol, self._nr_sw_vol_incr = 0, 0
        self._nr_sw_unvol, self._nr_sw_unvol_incr = 0, 0

        self._dt_last_contents = 0.0
        self._time_last_contents = 0.0

        self.refresh_contents()

    def alive(self) -> bool:
        if not self._alive:  # it died once...
            return False
        try:
            os.kill(self.pid, 0)
        except PermissionError:
            return True
        except ProcessLookupError:
            logg.warning(f'KTread::alive - pid {self.pid} has terminated.')
            self._alive = False
            return False
        else:
            return True

    def refresh_contents(self) -> None:
        logg.debug(f'KThread::refresh_contents - {self.pid}')

        self._comm = self.procfs_read('comm')[0]
        self._cpuset = self.procfs_read('cpuset')[0][1:]  # Remove heading /

        # Parse sched
        # scexao6: there are NUMA special lines without ":" at the end of the file
        # e.g. current_node=0, numa_group_id=0
        #      numa_faults node=0 task_private=0 task_shared=0 group_private=0 group_shared=0
        #      numa_faults node=1 task_private=0 task_shared=0 group_private=0 group_shared=0
        sched_info_lines = [
            l.split(':') for l in self.procfs_read('sched')[2:] if ':' in l
        ]

        self.sched_info: dict[str, str] = {
            l[0].strip(): l[1].strip()
            for l in sched_info_lines
        }

        runtime = float(self.sched_info['se.sum_exec_runtime'])
        self._runtime_incr, self._runtime = runtime - self._runtime, runtime

        migrations = int(self.sched_info['se.nr_migrations'])
        self._migrations_incr, self._migrations = migrations - self._migrations, migrations

        nr_sw = int(self.sched_info['nr_switches'])
        self._nr_sw_incr, self._nr_sw = nr_sw - self._nr_sw, nr_sw
        nr_sw_vol = int(self.sched_info['nr_voluntary_switches'])
        self._nr_sw_vol_incr, self._nr_sw_vol = nr_sw_vol - self._nr_sw_vol, nr_sw_vol
        nr_sw_unvol = int(self.sched_info['nr_involuntary_switches'])
        self._nr_sw_unvol_incr, self._nr_sw_unvol = nr_sw_unvol - self._nr_sw_unvol, nr_sw_unvol

        time_now = time.time()
        self._dt_last_contents = time_now - self._dt_last_contents
        self._time_last_contents = time_now

    @tl.root_decorator
    def procfs_write(self, file: str, content: str) -> None:
        tl.procfs_write(f'/proc/{self.pid}/{file}', content)

    def procfs_read(self, file: str) -> list[str]:
        return tl.procfs_read(f'/proc/{self.pid}/{file}')

    def __repr__(self) -> str:
        s = f'KThread pid {self.pid} - {self.name}'
        if self.kthread_type == KThreadTypeEnum.IRQ:
            s += f' - bound to IRQ {self._irq_number}'
        return s

    def register_interrupt(self, irq: IRQ) -> None:
        logg.info(
            f'KThread::register_interrupt - registering IRQ {irq.id} for {self.name} {self.pid}.'
        )
        self._irq_obj = irq

    def get_taskset(self) -> CPUSpec:
        try:
            affinity = os.sched_getaffinity(self.pid)
        except ProcessLookupError as exc:
            # This can raise if the process has died since creation
            self._alive = False
            affinity: set[int] = set()

        aff_str = tl.list_to_range_notation(list(affinity))
        logg.info(
            f'KThread::get_taskset - kt {self.name} {self.pid} lives on taskset {aff_str}.'
        )
        return CPUSpec(name=f'kt_anon@{self.pid}', cpu_list=list(affinity))

    @tl.root_decorator
    def pin_taskset(self, taskset: CPUSpec) -> None:
        logg.info(
            f'KThread::pin_taskset {self.name} {self.pid} onto CPUs {taskset.get_str()}'
        )
        cmd = f'taskset -pc {taskset.get_str()} {self.pid}'
        p = sproc.run(cmd.split(), stdout=sproc.PIPE, stderr=sproc.PIPE)
        if p.returncode != 0:
            logg.warning(
                f'KThread::pin_taskset {self.pid} ({self._comm}) failed (retcode {p.returncode})'
            )

    @tl.root_decorator
    def pin_cset(self, cpuset: CPUSpec) -> None:
        logg.info(
            f'KThread::pin_cset {self.name} {self.pid} onto CPUset {cpuset.name} {cpuset.get_str()}'
        )
        # Forcey cause sometimes bitchey
        cmd = f'-k -m --force {self.pid} root'
        tl.cset_proc_call(cmd)

        self.pin_taskset(cpuset)

        cmd = f'-k -m --force {self.pid} {cpuset.name}'
        tl.cset_proc_call(cmd)

        self.refresh_contents()
        now_cpuset = self.get_taskset()
        if set(now_cpuset.cpu_list) != set(cpuset.cpu_list):
            logg.error(
                f'KThread::pin_cset {self.pid} ({self._comm}): '
                f'failed to assign {cpuset.get_str()} - got {now_cpuset.get_str()}'
            )
        else:
            self.was_cset_successfully_once = True

    @tl.root_decorator
    def chrt_ff(self, rtprio: int) -> None:
        logg.info(
            f'KThread::chrt_ff {self.name} {self.pid} - priority {rtprio}.')
        cmd = f'chrt -f -p {rtprio} {self.pid}'
        p = sproc.run(cmd.split())

    @tl.root_decorator
    def chrt_oth(self) -> None:
        logg.info(f'KThread::chrt_oth {self.name} {self.pid}.')
        cmd = f'chrt -o -p 0 {self.pid}'
        p = sproc.run(cmd.split())
