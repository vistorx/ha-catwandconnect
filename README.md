<p align="center">
  <img src="https://raw.githubusercontent.com/vistorx/CatWandConnect/main/media/logo/logo-320.png" alt="CatWandConnect logo" width="160">
</p>

# CatWandConnect for Home Assistant

The Home Assistant integration for [CatWandConnect](https://github.com/vistorx/CatWandConnect), the open-hardware robot that plays with your cat by moving a toy wand.

> **Status: first release, being tested.** Needs CatWandConnect firmware **0.2.0-beta.2** or later and Home Assistant **2026.10** or later. The [MQTT connection](https://vistorx.github.io/CatWandConnect/home-assistant/) keeps working for any version.

## What it does

- **Finds the robot by itself.** Home Assistant shows it under *Discovered*; click **Add** and it's set up. No MQTT broker, no extra user.
- **Talks to it directly** on your local network, with live updates and no cloud.
- **Same entities as the MQTT connection:** Play session switch and Session duration, Stow button, Activity, position and maximum speed of each axis.
- **Joystick card** for your dashboards: hold and drag to move the wand, like the joystick on the robot's own page. See [Joystick card](#joystick-card).
- **Firmware updates** from Home Assistant: it tells you when a new robot firmware is out and installs it in one click. See [Firmware updates](#firmware-updates).
- **Ready-made dashboard**, documented on the CatWandConnect website.

The MQTT connection stays supported. Pick the one that suits you: this integration for the shortest setup, MQTT if you already run a broker.

## Installation

Through [HACS](https://hacs.xyz/), as a custom repository:

1. In Home Assistant, open **HACS**, the three dots at the top right, **Custom repositories**.
2. Add `https://github.com/vistorx/ha-catwandconnect` with the type **Integration**.
3. Search for **CatWandConnect** in HACS, **Download**, then restart Home Assistant.
4. The robot shows under **Settings → Devices & services → Discovered**. Click **Add** (or **Add integration → CatWandConnect** and type its IP address).

Full guide, dashboard and troubleshooting: [Home Assistant on the CatWandConnect website](https://vistorx.github.io/CatWandConnect/home-assistant/).

## Joystick card

The integration brings a dashboard card that works like the joystick on the robot's own page: put your finger on the pad and drag, the wand follows as long as you hold it, and it stops as soon as you let go. It works from anywhere Home Assistant does, including the mobile app away from home.

Edit a dashboard, **Add card**, and pick **CatWandConnect joystick** (nothing to add by hand: the integration adds the card to your dashboard resources itself, which the mobile app needs). Or in YAML:

```yaml
type: custom:catwandconnect-joystick-card
device_id: 0123456789abcdef0123456789abcdef  # the robot's device; the card editor picks it for you
title: Wand  # optional
```

Instead of `device_id` you can give `entity:` with any of the robot's entities, for example `entity: sensor.catwandconnect_activity`. Under the pad the card shows the Activity and the position of each axis; it greys out while the robot is offline.

Safety: the card repeats its command every 100 ms while you hold it, and the robot stops by itself if nothing arrives for half a second, so closing the app or losing the network never leaves the wand moving. Moving the joystick ends a running Play session, like on the robot's page.

After updating the integration, reload the dashboard page if the card doesn't show up. In the mobile app, if it shows "Configuration error", reset the app's frontend cache once: Settings → Companion app → Troubleshooting → **Reset frontend cache**. If your dashboards use YAML mode, add the resource yourself: `url: /catwandconnect/frontend/catwandconnect-joystick-card.js`, `type: module`.

## Firmware updates

Each robot has a **Firmware** update entity (`update.catwandconnect_firmware`, under the device's *Configuration*). It shows the firmware the robot runs and the latest one published for its Update channel (*Stable*, or *Beta* for a robot running a beta), and Home Assistant shows its usual "update available" badge in **Settings** when a newer one is out.

Click **Install**: Home Assistant downloads the firmware for the robot's chip from the CatWandConnect website, sends it to the robot (with the Settings PIN you stored, if you set one) and shows the progress. The robot restarts on the new version within about a minute; settings, Calibration and Wi-Fi are kept. If anything fails, the robot keeps running its current firmware.

- **Not during play.** Install is refused while the robot is in a Play session, a Calibration or a Speed tuning: stop it first.
- **Checked every 6 hours** and when Home Assistant starts. Without internet access, no update is offered, and nothing else changes.
- Robots on firmware older than the Update feed are offered updates too: their Update channel is taken from their version.

## What's new

See the [changelog](CHANGELOG.md). New versions are announced in the CatWandConnect Discord `#announcements` channel.

## Help and bug reports

Support for this integration happens in the main CatWandConnect repository, not here:

- **Bug in the integration:** [open an issue in CatWandConnect](https://github.com/vistorx/CatWandConnect/issues/new/choose), and pick *Home Assistant integration (HACS)* as the area.
- **Question or setup help:** the [CatWandConnect Discord](https://discord.gg/Rbqge3v9dk).
- **Security issue:** [report it privately](https://github.com/vistorx/CatWandConnect/security/advisories/new).

See [Getting help](https://vistorx.github.io/CatWandConnect/support/).

## Contributing

A change users notice adds a line under `## Unreleased` in `CHANGELOG.md`, written for them. Releasing `vX.Y.Z` needs that section renamed to the version: the release workflow turns it into the release notes and the Discord announcement. That workflow runs in the `release` environment and waits for the owner's approval (**Actions → Release → Review deployments**).

Pull requests are welcome here. For anything beyond a small fix, open an issue in [CatWandConnect](https://github.com/vistorx/CatWandConnect/issues) first so we can agree on the approach. The integration only uses the robot's documented [API](https://vistorx.github.io/CatWandConnect/api/); changes to the robot itself go to the main repository.

## Development

The integration lives in `custom_components/catwandconnect/`. Its tests run against a fake robot (`tests/fake_robot.py`), a local server speaking the documented API, so no hardware is needed. With [uv](https://docs.astral.sh/uv/) and Python 3.14:

```sh
uv venv -p 3.14
source .venv/bin/activate
uv pip install -r requirements_test.txt
pytest
```

CI runs these tests, [hassfest](https://developers.home-assistant.io/blog/2020/04/16/hassfest) and the [HACS validation](https://www.hacs.xyz/docs/publish/action/) on every pull request.

## Licence

[GPL-3.0-or-later](LICENSE), like the CatWandConnect firmware. "CatWandConnect" and its logo are reserved for the official project, see the [trademark policy](https://github.com/vistorx/CatWandConnect/blob/main/TRADEMARK.md).
