# systemd units

The units that actually run TechTrend on the VPS, as user services under
`idavoll` with linger enabled.

These live here because the worker's `--stage` list is deployment-critical and
was previously untracked: the notify stage was added to the running unit by
hand, so a rebuilt host would have deployed the code and silently not run it.

## Install

    mkdir -p ~/.config/systemd/user
    cp deploy/systemd/*.service ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now techtrend-worker techtrend-api techtrend-web \
                                 techtrend-slackbot
    loginctl enable-linger "$USER"    # survive logout

## After changing a unit here

    cp deploy/systemd/techtrend-worker.service ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user restart techtrend-worker

## Notes

- `techtrend-web` serves a **build**: run `pnpm build` before restarting it, or
  it serves the previous bundle.
- `techtrend-slackbot` holds an outbound WebSocket to Slack (Socket Mode) and
  answers @mentions in story threads. It needs `TT_SLACK_APP_TOKEN` (an
  app-level `xapp-` token) on top of the bot token, and exits immediately with
  a clear message if either is missing. It opens no inbound port.
- Secrets are not here. Every service reads `backend/.env`, which is gitignored.
