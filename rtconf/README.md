# rtconf subpackage -- standalone version

The complete version will be open-sourced at a later date.


## Userland install

`pip install -e .` at the root of the `swmain` repo. There's quite a bit of dependencies, so feel free to `pip install --no-deps -e .` instead, and cherry-pick the dependencies you actually need.

## Root install

Make sure you have `/usr/bin/python3` and `/usr/bin/pip3` ready to go (apt install `pip3`?). A good check is `sudo /usr/bin/pip3 list`

We don't install in dev mode in the root python distro (`pip install -e` would be BAD), as that would be insanely unsafe, since we have user-owned files (this folder) symlinked and executed with root privileges, but anyone has write permission into these...

```bash
sudo python3 -m pip install .
```

#### A nominative env.

You need an environment variable `WHICHCOMP` to identify which RT configuration to load. Define whatever you want for your machine and don't forget to add it to `find_right_config` in `rtconf.rtlinux_configs`

#### Make your own configuration

As you can see in `rtconf.rtlinux_configs`, we have:
- Flags defining bits and pieces of config to apply: max CPU performance, high real-time networking, IRQ parking, etc.
- A `my_cpusets` attributes that describes csets to create on the machine
- A `irq_kthread_special_rules` function that describes more detailed things to do with interrupts, kernel threads, possibly relating to special device drivers.
This is where you would define what should be done for your own PC!

## Testing?

#### First test:

`ipython -i rtconf.systemconfig -- --init`

Goal: obtain an interactive prompt with `devs`, `irqs`, and `kthreads`, which respctively describe the PCI devices, interrupts, and kernel threads found on the machine.
You must already have the `WHICHCOMP` set and have defined a corresponding config class.

#### Second test:

`ipython -i rtconf.systemconfig -- --forkcheck`

Goal: check that it successfully forks `systemconfig` with root privileges, that we have all the dependencies OK, and exit gracefully.

#### Third test:

Try to make a couple cpusets using these utilities!
