# zswap / swap reclaim tuning

## Diagnose cgroup swap usage

```
# Total memory and swap for a cgroup
cat /sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/session.slice/kitty-158562-3.scope/memory.current
cat /sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/session.slice/kitty-158562-3.scope/memory.swap.current

# Detailed breakdown (anon, file, zswapped, zswap pool size, etc.)
cat /sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/session.slice/kitty-158562-3.scope/memory.stat

# Per-process breakdown
cgroups-top --processes kitty-158562-3.scope -n 0
```

## memory.reclaim — what it actually does

```
echo "2g" > /sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/session.slice/kitty-158562-3.scope/memory.reclaim
```

Despite the name, this does NOT free swap space. It evicts pages from the zswap compressed RAM
pool to the backing swapfile on disk. Swap usage stays the same or increases; only the zswap
pool shrinks slightly.

To actually free swap space, processes holding those pages must exit.

## Tune zswap aggressiveness

Current defaults (Fedora Asahi):
- `max_pool_percent=50` — zswap can use up to 50% of RAM for compressed pages
- `shrinker_enabled=Y` — kernel proactively shrinks pool under pressure
- `swappiness=80`

```
# Reduce zswap pool size to force earlier eviction (runtime, resets on reboot)
echo 10 > /sys/module/zswap/parameters/max_pool_percent

# Reduce swappiness to make kernel less eager to swap out (runtime)
sysctl vm.swappiness=20
```

## Persistent system config files

Current persistent settings are tracked in these files:

`/etc/modprobe.d/zswap.conf`
```
options zswap max_pool_percent=10
```
Boot-time zswap module parameters; `max_pool_percent=10` limits compressed swap cache usage in RAM.

`/etc/sysctl.d/31-swappiness.conf`
```
vm.swappiness = 20
```
Persistent VM tuning; `vm.swappiness = 20` reduces how eagerly the kernel swaps compared to higher defaults.

`/etc/systemd/logind.conf`
```
[Login]
HandlePowerKey=suspend
HandlePowerKeyLongPress=poweroff
HandleSuspendKey=ignore
```
`systemd-logind` power policy; power key suspends, long press powers off, suspend key is ignored.

`/etc/systemd/system/tmp.mount.d/override.conf`
```
[Mount]
Options=mode=1777,relatime,size=8G
```
`tmp.mount` drop-in override; keeps `/tmp` as tmpfs with size 8G instead of the default 16G.

## Notes

- zswap is a compressed in-RAM cache in front of real swap. High compression ratios (~98%) mean
  it's holding a lot of data cheaply, so there's less urgency to evict.
- Swap pages from exited processes remain charged to their cgroup until the kernel reclaims them.
  This is expected — not a bug.
- `swapoff -a && swapon -a` forces all swap back into RAM at once; use only if swap space is
  running out and you have enough free RAM.

---

## Temporary directory (/tmp) — tmpfs size

If /tmp is mounted as tmpfs, limit its maximum size to 8G to avoid reserving excessive RAM.

Check current state:

```
df -h /tmp
mount | grep ' /tmp '
systemctl status tmp.mount || true
```

One-off (immediate):

```
# Ensure current usage is under 8G before shrinking:
df -h /tmp
sudo mount -o remount,size=8G /tmp
```

Persist via systemd tmp.mount drop-in:

```
sudo mkdir -p /etc/systemd/system/tmp.mount.d
sudo tee /etc/systemd/system/tmp.mount.d/override.conf > /dev/null <<'EOF2'
[Mount]
Options=mode=1777,strictatime,size=8G
EOF2
sudo systemctl daemon-reload
sudo systemctl restart tmp.mount
```


Warning: Shrinking /tmp below its current usage will cause writes to fail; ensure /tmp usage is below the new size before remounting or free files in /tmp.
