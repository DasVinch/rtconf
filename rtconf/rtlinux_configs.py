from __future__ import annotations

import typing as typ
if typ.TYPE_CHECKING:
    from .irqs import IRQ

import os
import glob
import logging

logg = logging.getLogger(__name__)

from abc import ABC

from .cset import CPUSpec
from . import tools as tl
from .kthread import KThread, KThreadTypeEnum
from . import functions


class BaseConfig(ABC):

    singleton_instantiated = False

    TEST = True
    HYPERTHREADING_SOFTDISABLE = True
    NETWORK_GENERIC = True
    NETWORK_LANS = True

    CPUSETS = False

    CUSTOM_IRQ_RULES = False

    IRQ_PARKING = False
    RESTART_IRQBALANCE = False  # We never stopped it...

    PERFORMANCE = False

    DMA_LATENCY = False

    my_cpusets: list[CPUSpec] = []
    cpus_no_balancing: CPUSpec | None = None
    irqs_nobalancing: set[IRQ] = set()

    def __init__(self) -> None:
        # Enforce the singleton - by failure, not by returning the singleton instance.
        logg.info(f'Calling BaseConfig __init__ from subclass {type(self)}')
        _subdir_members = self.__dir__()
        _subdir_members = {
            v: getattr(self, v)
            for v in self.__dir__() if not v.startswith('__')
        }
        logg.info(f'Class variable configuration: {_subdir_members}')

        if BaseConfig.singleton_instantiated:
            logg.critical('Double-init on supposedly singleton class.')
            raise AssertionError(
                'Re-instantiating what should be a singleton.')

        BaseConfig.singleton_instantiated = True

        # Assign default cpusets and check consistency with grub line.

        self.all_cpus = CPUSpec('root',
                                cpu_list=list(tl.ALL_CPUS),
                                mem_list=list(range(tl.MEMORY_COUNT)))
        cmdline = tl.procfs_read('/proc/cmdline')[0].split(' ')
        s_isolcpus = ''
        import re
        for c in cmdline:
            if c.startswith('isolcpus='):
                isol_specs = c.split('=')[1].split(',')
                s_isolcpus = ','.join([
                    s for s in isol_specs
                    if re.search('^[0-9]+(\-[0-9]+)?$', s)
                ])
                break

        # Togo logg a warning if we didn't find anything.

        self.all_reserved_cpus = CPUSpec(name='reserved',
                                         str_spec=s_isolcpus,
                                         mem_list=self.all_cpus.mem_list)

        # System CPUs must be the non-isolated ones.
        self.all_system_cpus = CPUSpec(
            name='system',
            cpu_list=list(
                set(self.all_cpus.cpu_list) -
                set(self.all_reserved_cpus.cpu_list)),
            mem_list=self.all_cpus.mem_list)

        cpus_no_balancing = set(self.all_reserved_cpus.cpu_list)
        for cset in self.my_cpusets:
            if cset.no_irqbalance:
                cpus_no_balancing.update(cset.cpu_list)

        self.cpus_no_balancing = CPUSpec('nobalance',
                                         cpu_list=list(cpus_no_balancing))

        self.my_cpusets_dict = {cset.name: cset for cset in self.my_cpusets}

    def irq_kthread_special_rules(self, irq_list: list[IRQ],
                                  kt_list: list[KThread]) -> None:
        logg.critical(
            'irq_kthread_special_rules @ BaseConfig must be subclassed.')
        raise AssertionError('Must implement if using cfg.CUSTOM_IRQ_RULES')


class RTCConfig(BaseConfig):

    CPUSETS = True

    IRQ_PARKING = True
    RESTART_IRQBALANCE = True

    DMA_LATENCY = True


class SC5Config(RTCConfig):

    CUSTOM_IRQ_RULES = True

    PERFORMANCE = True

    # TODO: where do we park Hiperf NVME? Basic DiskIO?

    # yapf: disable
    my_cpusets = [
        # 0-5 SYSTEM

        # o for OCAM (EDT numa 0)
        CPUSpec('o_work', cpu_list=[6], mem_list=[0], no_irqbalance=True),

        # Mellanox IRQs only
        CPUSpec('irq_mlx_safe', cpu_list=[7], mem_list=[0,1], no_irqbalance=True),

        # Mellanox kthreads - maybe 2 cores are a good idea here. But should we let the scheduler
        # Work it?
        CPUSpec('kt_mlx_safe', cpu_list=[8], mem_list=[0,1], no_irqbalance=True),

        # 9 unused

        # Housekeeping RCU - ALSO on 29
        CPUSpec('kt_rcu_safe', cpu_list=[10, 29], mem_list=[0,1], no_irqbalance=True),

        # a for apapane (EDT numa 0)
        CPUSpec('a_edt', cpu_list=[11], mem_list=[0], no_irqbalance=True),
        CPUSpec('a_utr', cpu_list=[12], mem_list=[0], no_irqbalance=True),
        CPUSpec('a_tcp', cpu_list=[13], mem_list=[0], no_irqbalance=True),

        # v for (New) Vampires CAM 2 (ASL numa 0)
        CPUSpec('v2_asl', cpu_list=[14], mem_list=[1], no_irqbalance=True),
        CPUSpec('v2_tcp', cpu_list=[15], mem_list=[1], no_irqbalance=True),

        # 16-17 available

        # p for palila (EDT numa 1)
        CPUSpec('p_edt', cpu_list=[22], mem_list=[1], no_irqbalance=True),
        CPUSpec('p_utr', cpu_list=[23], mem_list=[1], no_irqbalance=True),
        CPUSpec('p_tcp', cpu_list=[24], mem_list=[1], no_irqbalance=True),

        # k for kiwikiu (EDT numa 1) - FIXME possibly we can use only 1 cset
        CPUSpec('k_work', cpu_list=[25], mem_list=[1], no_irqbalance=True),

        # g for glint (EDT numa 1)
        CPUSpec('g_work', cpu_list=[26], mem_list=[1], no_irqbalance=True),

        # v for (New) Vampires CAM 1 (ASL numa 1)
        CPUSpec('v1_asl', cpu_list=[27], mem_list=[1], no_irqbalance=True),
        CPUSpec('v1_tcp', cpu_list=[28], mem_list=[1], no_irqbalance=True),

        # 29 used by RCU


        # q for orcaquest being pre-tested (2023-03)
        CPUSpec('q_asl', cpu_list=[30], mem_list=[1], no_irqbalance=True),
        CPUSpec('q_tcp', cpu_list=[31], mem_list=[1], no_irqbalance=True),

        # 32-34 available.

        # RTmon
        CPUSpec('RTmon', cpu_list=[35], mem_list=[1], no_irqbalance=True),
    ]
    # yapf: enable

    def irq_kthread_special_rules(self, irq_list: list[IRQ],
                                  kt_list: list[KThread]) -> None:

        logg.info('irq_kthread_special_rules @ SC5Config')

        edt_objs = functions.identify_fg_objs(irq_list, driver='edt')
        assert len(edt_objs) == 5
        self.irqs_nobalancing.update({e.irq for e in edt_objs})
        # Bind
        edt_objs[0].bind_to_cset(self.my_cpusets_dict['o_work'], ktprio=49)
        edt_objs[1].bind_to_cset(self.my_cpusets_dict['a_edt'], ktprio=49)
        edt_objs[2].bind_to_cset(self.my_cpusets_dict['k_work'], ktprio=49)
        edt_objs[3].bind_to_cset(self.my_cpusets_dict['p_edt'], ktprio=49)
        edt_objs[4].bind_to_cset(self.my_cpusets_dict['g_work'], ktprio=49)

        asl_objs = functions.identify_fg_objs(irq_list, driver='aslenum')
        assert len(asl_objs) == 2
        self.irqs_nobalancing.update({e.irq for e in asl_objs})
        asl_objs[0].bind_to_cset(self.my_cpusets_dict['v2_asl'])
        asl_objs[1].bind_to_cset(self.my_cpusets_dict['v1_asl'])

        for irq in irq_list:
            if irq.pci_device and irq.pci_device.driver == 'mlx5_core':
                irq.set_pin_to_cpu(
                    self.my_cpusets_dict['irq_mlx_safe'].cpu_list)
                self.irqs_nobalancing.add(irq)

        for kt in kt_list:
            if 'mlx5' in kt.name:
                kt.pin_cset(self.my_cpusets_dict['kt_mlx_safe'])
                kt.chrt_ff(60)

            elif kt.kthread_type == KThreadTypeEnum.RCUC:
                kt.chrt_ff(30)

            elif kt.kthread_type in [
                    KThreadTypeEnum.RCUB, KThreadTypeEnum.RCUOG,
                    KThreadTypeEnum.RCUOP
            ]:
                kt.pin_cset(self.my_cpusets_dict['kt_rcu_safe'])
                kt.chrt_ff(30)


class SC6Config(RTCConfig):

    CUSTOM_IRQ_RULES = True
    CUSTOM_KTHREAD_RULES = True

    PERFORMANCE = True

    def irq_kthread_special_rules(self, irq_list: list[IRQ],
                                  kt_list: list[KThread]) -> None:
        logg.info('irq_kthread_special_rules @ SC6Config')
        pass


class AORTSConfig(RTCConfig):

    CUSTOM_IRQ_RULES = True

    PERFORMANCE = True

    # WARNING: CPUS ARE INTERLEAVED
    # yapf: disable
    my_cpusets = [
        # EVEN CPUS (NUMA 0) (0-38:2)
        # 0,2,4,6,8,10 SYSTEM (6 numa 0, 6 numa 1)

        # RT misc
        CPUSpec('aolrt', cpu_list=[12,14,16,18,20], mem_list=[0], no_irqbalance=True),

        # DM188 comb / sim comb
        CPUSpec('dm188_comb', cpu_list=[22], mem_list=[0], no_irqbalance=True),

        # FPDP DM drv
        CPUSpec('dm188_drv', cpu_list=[24], mem_list=[0], no_irqbalance=True),

        # FPDP receive IRQ / KT / APDs
        CPUSpec('fpdp_recv', cpu_list=[26], mem_list=[0], no_irqbalance=True),

        # FPDP receive if second channel of receive (e.g. DM trans mode)
        CPUSpec('fpdp_recv2', cpu_list=[28], mem_list=[0], no_irqbalance=True),

        # IRQ ALPAO net enp2
        CPUSpec('irq_enp2', cpu_list=[30], mem_list=[0], no_irqbalance=True),

        # KT ALPAO net enp2
        CPUSpec('kt_enp2', cpu_list=[32], mem_list=[0], no_irqbalance=True),

        # IRQ ALPAO net enp5
        CPUSpec('irq_enp5', cpu_list=[34], mem_list=[0], no_irqbalance=True),

        # KT ALPAO net enp5
        CPUSpec('kt_enp5', cpu_list=[36], mem_list=[0], no_irqbalance=True),

        # Housekeeping RCU - ALSO on 37
        CPUSpec('kt_rcu', cpu_list=[38, 37], mem_list=[0,1], no_irqbalance=True),

        #===============
        # ODD CPUS (NUMA 1) (1-39:2)
        # 1,3,5,7,9,11 SYSTEM (6 numa 0, 6 numa 1)


        CPUSpec('i_mvm2', cpu_list=[15], mem_list=[1], no_irqbalance=True),
        CPUSpec('i_mvm', cpu_list=[17], mem_list=[1], no_irqbalance=True),
        CPUSpec('i_mfilt', cpu_list=[19], mem_list=[1], no_irqbalance=True),
        CPUSpec('i_acq_wfs', cpu_list=[21], mem_list=[1], no_irqbalance=True),

        # Telemetry TCP, low amounts
        CPUSpec('other_tcp', cpu_list=[23], mem_list=[1], no_irqbalance=True),

        # RT loggers - don't change name without changing log_shim_fixer
        CPUSpec('aollog', cpu_list=[25, 27, 29, 31], mem_list=[0, 1], no_irqbalance=True),

        # 33: iiwi fgrab
        CPUSpec('i_edt', cpu_list=[33], mem_list=[1], no_irqbalance=True),

        # 35: iiwi tcp
        CPUSpec('i_tcp', cpu_list=[35], mem_list=[1], no_irqbalance=True),

        # 37 For kt_rcu_safe (38)

        # 39 RTmon
        CPUSpec('RTmon', cpu_list=[39], mem_list=[1], no_irqbalance=True),
    ]
    # yapf: enable

    def irq_kthread_special_rules(self, irq_list: list[IRQ],
                                  kt_list: list[KThread]) -> None:
        logg.info('irq_kthread_special_rules @ AORTSConfig')

        for irq in irq_list:
            irq.was_pinned_successfully_once = False

        edt_objs = functions.identify_fg_objs(irq_list, driver='edt')
        assert len(edt_objs) == 1
        self.irqs_nobalancing.update({e.irq for e in edt_objs})
        edt_objs[0].bind_to_cset(self.my_cpusets_dict['i_edt'], ktprio=49)

        fpdp_objs = functions.identify_fg_objs(irq_list,
                                               driver='dcfi_nsl_module')
        assert len(fpdp_objs) == 1
        self.irqs_nobalancing.update({e.irq for e in fpdp_objs})
        fpdp_objs[0].bind_to_cset(self.my_cpusets_dict['fpdp_recv'], ktprio=49)

        asl_objs = functions.identify_fg_objs(irq_list, driver='aslenum')
        assert len(asl_objs) == 1
        self.irqs_nobalancing.update({e.irq for e in asl_objs})
        asl_objs[0].bind_to_cset(
            self.my_cpusets_dict['fpdp_recv2'])  # FIXME add cset

        for irq in irq_list:
            if irq.pci_device and irq.pci_device.net_iface.startswith('enp2'):
                irq.set_pin_to_cpu(self.my_cpusets_dict['irq_enp2'].cpu_list)
                self.irqs_nobalancing.add(irq)
            elif irq.pci_device and irq.pci_device.net_iface.startswith(
                    'enp5'):
                irq.set_pin_to_cpu(self.my_cpusets_dict['irq_enp5'].cpu_list)
                self.irqs_nobalancing.add(irq)

        for kt in kt_list:
            if 'enp2' in kt.name:
                kt.pin_cset(self.my_cpusets_dict['kt_enp2'])
                kt.chrt_ff(60)
            if 'enp5' in kt.name:
                kt.pin_cset(self.my_cpusets_dict['kt_enp5'])
                kt.chrt_ff(60)

            elif kt.kthread_type == KThreadTypeEnum.RCUC:
                kt.chrt_ff(30)

            elif kt.kthread_type in [
                    KThreadTypeEnum.RCUB, KThreadTypeEnum.RCUOG,
                    KThreadTypeEnum.RCUOP
            ]:
                kt.pin_cset(self.my_cpusets_dict['kt_rcu'])
                kt.chrt_ff(30)

        # FIXME need to adress making a nvidia safe space.
        # FIXME need to handle and figure out the FPDP kthreads and interrupts, if any??


def find_right_config() -> BaseConfig:

    logg.info('find_right_config()')

    # We want to be able to get this even from a root session.
    WHICHCOMP: str = ''
    if os.getuid() != 0:
        WHICHCOMP = os.environ.get(
            'WHICHCOMP',
            '')  # This is a server ID, provided by the shell environment
    else:  # root
        import subprocess as sproc
        main_user = sproc.run(f'getent passwd 1000 | cut -d : -f 1',
                              shell=True,
                              stdout=sproc.PIPE).stdout.decode().rstrip()
        WHICHCOMP = sproc.run(
            f'sudo -Hiu {main_user} echo \$WHICHCOMP',
            shell=True,
            stdout=sproc.PIPE).stdout.decode().split('\n')[-2].rstrip()

    if WHICHCOMP == '':
        logg.critical(
            'find_right_config: WHICHCOMP environment variable not found.')
        raise AssertionError(
            'find_right_config: WHICHCOMP environment variable not found.')

    logg.info(f'Found WHICHCOMP = {WHICHCOMP}')

    config_class_dict: dict[str, type[BaseConfig]] = {
        '5': SC5Config,
        '6': SC6Config,
        'AORTS': AORTSConfig,
        'UNICORN': RTCConfig
    }

    return config_class_dict[WHICHCOMP]()  # Instantiate.


SYSCTL_TWEAK_LIST_NETWORK: list[tuple[str, str | int]] = [
    ('net.core.netdev_max_backlog', 250000),
    ('net.core.rmem_max', 16777216),
    ('net.core.wmem_max', 16777216),
    ('net.core.rmem_default', 16777216),
    ('net.core.wmem_default', 16777216),
    ('net.core.optmem_max', 16777216),
    ('net.ipv4.tcp_low_latency', 1),
    ('net.ipv4.tcp_sack', 0),
    ('net.ipv4.tcp_timestamps', 0),
    ('net.ipv4.tcp_fastopen', 1),
    ('net.ipv4.tcp_mem', '16777216 16777216 16777216'),
    ('net.ipv4.tcp_rmem', '4096 87380 16777216'),
    ('net.ipv4.tcp_wmem', '4096 65536 16777216'),
    ('net.ipv6.tcp_low_latency', 1),
    ('net.ipv6.tcp_sack', 0),
    ('net.ipv6.tcp_timestamps', 0),
    ('net.ipv6.tcp_fastopen', 1),
]

# File, enable value, disable value
SYSCTL_TWEAK_LIST_CPUPERF: list[tuple[str, str | int, str | int]] = [
    ('/proc/sys/vm/stat_interval', 1000, 1),
    ('/proc/sys/vm/dirty_writeback_centisecs', 5000, 500),
    ('/proc/sys/kernel/watchdog', 0, 1),
    ('/proc/sys/kernel/nmi_watchdog', 0, 1),
    ('/proc/sys/kernel/sched_rt_runtime_us', 995000, 950000
     )  # Could be -1 but actually probs antiproductive.
]
SYSCTL_TWEAK_LIST_CPUPERF += [
    (machine_check_file, 0, 300) for machine_check_file in glob.glob(
        '/sys/devices/system/machinecheck/machinecheck*/check_interval')
]
