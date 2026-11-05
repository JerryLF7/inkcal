# redroid 拖死宿主机（2026-10 故障记录）

> 适用范围：`scripts/burn_sources/heytap_ui.py` 依赖的 redroid 容器，以及 `~/Docker/redroid/` 这套运行环境。
> 状态：**已修复并验证**（2026-10-26）。

## 摘要

redroid 容器在宿主机上启动约 **5 分钟**后，整机硬冻结：鼠标键盘无响应、SSH 不可达、ARP 不回，只能手动断电。

根因不是硬件、不是内核版本、不是 FlClash，而是 **binder 模块开机从未加载**，导致容器内 Android init 触发 `reboot_on_failure`，把 `reboot()` 系统调用打到了宿主内核。

## 症状

| 项目 | 表现 |
|---|---|
| 触发时间 | 开机后约 2–5 分钟，6 次复现全部落在 4:43 – 5:10 之间 |
| 输入 | 鼠标键盘完全无响应，屏幕停在最后一帧 |
| 网络 | SSH 超时；同网段 ARP `FAILED` / `INCOMPLETE` |
| 日志 | journal / dmesg 在正常刷屏中**戛然而止**，无 oops、无 panic、无 thermal、无 OOM |
| 恢复 | 只能短按电源键断电重启 |

用 netconsole 把内核日志实时发到 NAS，最后一次抓包停在容器启动后 **283 秒**，随后永久中断——说明系统是在内核层“静默死亡”，不是用户态崩溃。

## 根因

`/etc/modules-load.d/redroid.conf` 内容错误，导致 `binder_linux` 开机加载失败：

```
\ufeffbinder_linux devices="binder,hwbinder,vndbinder"
```

两个错误叠加：

1. 文件开头有 **UTF-8 BOM**（`ef bb bf`），systemd 把它当成模块名的一部分；
2. `systemd-modules-load` **不支持模块参数**，它把整行当作模块名去查找。

开机日志原文：

```
systemd-modules-load: Failed to find module 'binder_linux devices="binder,hwbinder,vndbinder"'
```

### 为什么 9/24 – 10/22 一直没事

安装脚本当时手动执行过一次 `modprobe binder_linux`，模块常驻内核，因此**连续 28 天**运行正常。10/22 第一次重启后模块没有自动加载，问题才暴露——这也是为什么最初会误判成“升级引入的回归”。

### 致死链条

```
binder 模块未加载
  → 宿主无 /dev/binder、/dev/hwbinder、/dev/vndbinder
    → 容器内 servicemanager 起不来
      → hwservicemanager、vold 相继失败
        → Android init 执行 reboot_on_failure
          → reboot() 不受 namespace 隔离，特权容器拥有 CAP_SYS_BOOT
            → 宿主内核进入重启流程，device_shutdown() 停掉网卡/磁盘/USB
              → 卡在半路：灯亮、画面冻结、ARP 不回、日志中断
```

容器内 init 的关键日志：

```
init: Service vold has 'reboot_on_failure' option and failed, shutting down system.
init: Got shutdown_command 'reboot,vold-failed' Calling HandlePowerctlMessage()
init: Reboot start, reason: reboot,vold-failed, reboot_target: vold-failed
init: powerctl_shutdown_time_ms:970:0
init: Reboot ending, jumping to kernel
```

`shutdown_timeout_timespec.tv_sec: 319`（≈5.3 分钟）就是死亡时间固定的原因。

## 已排除的方向

| 方向 | 依据 |
|---|---|
| 硬件 / 过热 / 供电 | 温度 40°C，风扇正常；内存 1.9G/7.6G，无 OOM |
| 内核回归 | 6.12.113 与 6.12.101 **两个内核都复现** |
| 图形栈 | 用 `systemd.unit=multi-user.target` 无图形启动，仍然复现 |
| FlClash / TUN | 完全不启动 FlClash 时仍复现 |
| KVM 切换 | 未切换 KVM 的那次同样复现 |
| SSH / 网络服务 | ARP 都不回，属于链路层失联，与 sshd 无关 |

停掉 redroid 容器后，同一台机器连续稳定 **30 分钟**，反向验证成立。

## 修复内容（宿主机侧，四层）

| 文件 | 内容 | 作用 |
|---|---|---|
| `/etc/modules-load.d/redroid.conf` | `binder_linux` | 开机加载模块（去 BOM、去参数） |
| `/etc/modprobe.d/redroid-binder.conf` | `options binder_linux devices=binder,hwbinder,vndbinder` | 创建三个 misc 设备 |
| `/etc/udev/rules.d/60-binder.rules` | 三个节点 `MODE="0666"` | 权限持久化 |
| `/etc/systemd/system/redroid-post-start.service` | 开机执行 `~/Docker/redroid/scripts/post-start.sh` | 替代原来必须手工补跑的一步 |

`redroid-post-start.service` 的要点：`User=jerry` + `SupplementaryGroups=docker`，`After=docker.service network-online.target`，`Type=oneshot` + `RemainAfterExit=yes`，`TimeoutStartSec=600`。脚本内部自带重试循环，能等到容器起来。

## 验证

修复后连续两次重启，全程无人工介入：

```
/dev/binder /dev/hwbinder /dev/vndbinder   全部 crw-rw-rw-
模块参数                                   binder,hwbinder,vndbinder
容器                                       redroid Up
redroid-post-start.service                 Finished (status=0/SUCCESS)
sys.boot_completed                         1
adb devices                                192.168.5.158:5555  device
```

第一次修复后连续运行 **9 小时 47 分**，第二次重启后同样越过 5 分钟死亡窗口。

## 重要教训：不要在容器层“加固”

`--privileged` 会让以下两种常见限制**静默失效**，别再把它们当防线：

| 手段 | 实测结果 |
|---|---|
| `--cap-drop=SYS_BOOT` | 容器内 `CapEff=000001ffffffffff`，`SYS_BOOT` 仍在（bit 22 未摘） |
| `--security-opt seccomp=<拒绝 reboot 的规则>` | 容器内 `Seccomp: 0`，过滤器根本没加载 |

**真正的防线是让 binder 正常工作**，使 Android init 根本不进入关机流程。

另外：Debian 内核 `CONFIG_ANDROID_BINDERFS` 未开启，`mount -t binder` 会报 `unknown filesystem type`。只能依赖 misc 设备（`/sys/class/misc/{binder,hwbinder,vndbinder}`），不要照搬需要 binderfs 的教程。

## 复发排查清单

按顺序执行，任一步失败就停在那里，不要继续启动容器：

```bash
# 1. 三个节点是否存在、权限是否 666
ls -l /dev/binder /dev/hwbinder /dev/vndbinder

# 2. 模块是否加载、参数是否正确
lsmod | grep binder_linux
cat /sys/module/binder_linux/parameters/devices

# 3. 启动容器 + 补做伪装
cd ~/Docker/redroid && ~/.local/bin/docker-compose up -d
sudo systemctl restart redroid-post-start

# 4. Android 是否真正启动完成、adb 是否连上
docker exec redroid getprop sys.boot_completed
adb devices
```

若第 1 步节点消失（例如内核升级后 modules-load 又失效）：**立刻停掉容器**，否则会回到 `reboot_on_failure` 那条路径，5 分钟后宿主机会再次卡死。

## 相关文件

- `~/Docker/redroid/docker-compose.yml` — 容器定义（`privileged: true`，`restart: unless-stopped`）
- `~/Docker/redroid/scripts/post-start.sh` — binder 权限 + root 伪装 + adb 连接
- `~/Docker/redroid/README.md` — 该目录自身的运维说明
- `scripts/burn_sources/heytap_ui.py` — 消费 adb 的业务脚本（`REDROID_SERIAL`）
