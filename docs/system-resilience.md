# System Resilience: Reboot-on-Failure for myRSSfeed

## Problem

myRSSfeed depends on ollama for AI summarization. When ollama hangs (typically
during inference with large models), the Python process can stall indefinitely
without ever exiting. Standard `Restart=on-failure` only triggers when the
process *exits* — a hung process never exits, so the service stays stuck and
the device becomes unresponsive.

When the service does eventually fail and exhaust its restart attempts, systemd
marks it `failed` and stops trying. This leaves the device running but the
service permanently dead until someone manually restarts it.

## Solution

Three additions to the systemd unit beyond the defaults:

```ini
[Unit]
StartLimitBurst=3           # allow 3 restart attempts…
StartLimitIntervalSec=300   # …within a 5-minute window before giving up

[Service]
TimeoutSec=300              # kill the process if it hangs for >5 minutes
FailureAction=reboot        # reboot the device when restart limit is exhausted
```

### What each setting does

| Setting | Effect |
|---|---|
| `TimeoutSec=300` | Sends SIGTERM (then SIGKILL) to the process if it doesn't exit within 5 minutes. This converts a silent hang into a detectable failure. |
| `StartLimitBurst=3` / `StartLimitIntervalSec=300` | Allows up to 3 restart attempts in a 5-minute window before systemd stops retrying. |
| `FailureAction=reboot` | When the service enters the `failed` state (restart limit exhausted), triggers a clean system reboot instead of leaving the device in a broken state. The service is `WantedBy=multi-user.target`, so it starts automatically after reboot. |

### Failure flow

```
service hangs
    → TimeoutSec fires → SIGTERM/SIGKILL → process exits (failure)
    → systemd restarts (Restart=on-failure, up to 3× in 5 min)
    → if still failing → service enters "failed" state
    → FailureAction=reboot → clean reboot
    → service starts fresh on boot
```

## Trade-offs

- **Unexpected reboots**: If the service fails for a non-transient reason (bad
  code, missing config), the device will reboot in a loop. Check
  `journalctl -u myrssfeed -b -1` (previous boot) to diagnose before the next
  reboot window.
- **5-minute hang tolerance**: `TimeoutSec=300` means a legitimate slow model
  pull or heavy inference run could be killed prematurely. Adjust to match
  your slowest expected model response time.
- **Not default OS behavior**: Rebooting on application failure is not typical.
  This is appropriate here because myRSSfeed is the sole purpose of this
  device and human intervention is not always available.

## Applying manually (idempotent)

Run the resilience configuration script from the repo root:

```bash
bash scripts/configure-resilience.sh
```

The script is idempotent — safe to run multiple times. It writes the same unit
file as `install.sh` would write when you answer `y` to the resilience prompt.

## Disabling

To revert to standard behaviour (no auto-reboot):

```bash
sudo sed -i '/StartLimitBurst\|StartLimitIntervalSec/d' /etc/systemd/system/myrssfeed.service
sudo sed -i '/TimeoutSec\|FailureAction/d' /etc/systemd/system/myrssfeed.service
sudo systemctl daemon-reload
```
