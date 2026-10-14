<p align="center">
  <img src="https://raw.githubusercontent.com/vistorx/CatWandConnect/main/media/logo/logo-320.png" alt="CatWandConnect logo" width="160">
</p>

# CatWandConnect for Home Assistant

The Home Assistant integration for [CatWandConnect](https://github.com/vistorx/CatWandConnect), the open-hardware robot that plays with your cat by moving a toy wand.

> **Status: in development, planned for CatWandConnect V2.** Nothing to install yet. Today, connect the robot to Home Assistant over MQTT: see [Set up Home Assistant](https://vistorx.github.io/CatWandConnect/home-assistant/).

## What it will do

- **Finds the robot by itself.** Home Assistant shows it under *Discovered*; click **Add** and it's set up. No MQTT broker, no extra user.
- **Talks to it directly** on your local network, with live updates and no cloud.
- **Same entities as the MQTT connection:** Play session switch and Session duration, Stow button, Activity, position and maximum speed of each axis.
- **Ready-made dashboard**, documented on the CatWandConnect website.

The MQTT connection stays supported. Pick the one that suits you: this integration for the shortest setup, MQTT if you already run a broker.

## Installation

Through [HACS](https://hacs.xyz/), once the first release is out. The steps will be on the [CatWandConnect website](https://vistorx.github.io/CatWandConnect/home-assistant/).

## Help and bug reports

Support for this integration happens in the main CatWandConnect repository, not here:

- **Bug in the integration:** [open an issue in CatWandConnect](https://github.com/vistorx/CatWandConnect/issues/new/choose), and pick *Home Assistant integration (HACS)* as the area.
- **Question or setup help:** the [CatWandConnect Discord](https://discord.gg/Rbqge3v9dk).
- **Security issue:** [report it privately](https://github.com/vistorx/CatWandConnect/security/advisories/new).

See [Getting help](https://vistorx.github.io/CatWandConnect/support/).

## Contributing

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
