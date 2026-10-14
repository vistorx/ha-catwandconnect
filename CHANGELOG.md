# Changelog

What changed in each version of the CatWandConnect integration for Home Assistant. HACS offers each new version under **HACS → CatWandConnect → Update**; restart Home Assistant afterwards.

## Unreleased

- **Joystick card.** Add *CatWandConnect joystick* to a dashboard and move the wand with your finger, like on the robot's own page: it follows while you hold, and stops when you let go or close the app. It shows the Activity and positions, and greys out while the robot is offline. See [Joystick card](https://github.com/vistorx/ha-catwandconnect#joystick-card).

## 0.1.0 - 2026-10-14

**Your robot in Home Assistant, without MQTT.** The integration finds CatWandConnect on your network by itself: click **Add**, and the Play session, Stow, positions and speeds are on your dashboard, updated live within a second.

### Highlights

- **Found by itself.** The robot shows under *Discovered*; or add it by IP address or `.local` name. Type the Settings PIN only if you set one.
- **Eight entities, live:** Play session switch and Session duration, Stow button, Activity, position and maximum speed of each axis, in English and French.
- **Looks after itself.** It reconnects after a power cut, asks for the new PIN when you change it, and tells you plainly when the robot's firmware needs an update.
- **Help made easy.** Download redacted diagnostics from the integration's page and attach them to a [bug report](https://github.com/vistorx/CatWandConnect/issues/new/choose).
- **Ready-made dashboard** to copy and paste, in the [Home Assistant guide](https://vistorx.github.io/CatWandConnect/home-assistant/).

### Requirements

CatWandConnect firmware 0.2.0-beta.2 or later, Home Assistant 2026.10 or later, and [HACS](https://hacs.xyz/).
