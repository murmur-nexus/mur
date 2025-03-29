![mur](https://github.com/murmur-nexus/murmur/blob/main/docs/docs/assets/mur-header-github.png)

![PyPI - Version](https://img.shields.io/pypi/v/mur)
![PyPI - License](https://img.shields.io/pypi/l/mur)
![Mur - Able](https://github.com/murmur-nexus/murmur/blob/main/docs/docs/assets/mur-able-badge.png)

# mur
A simple CLI to manage tools on your MCP (Model Context Protocol) server. 

## Install

```bash
pip install mur 
```

## Quickstart

- Host your own MCP with [capsule](https://github.com/murmur-nexus/capsule)
- [Find some tools](https://artifacts.murmur.nexus) or [build your own](https://murmur-nexus.github.io/murmur/how-to/create-a-tool/)
- Manage tools using `mur` commands

## Commands

### `mur install`

Install one or more tools into your MCP

```bash
mur install TOOL --host HOST
```

- `TOOL`: Name of the tool or toolkit to install e.g. [get_weather](https://artifacts.murmur.nexus/ewg/get_weather)
- `HOST`: Host URL from where you want to install e.g. `http://localhost:8000`

### `mur uninstall`

Uninstall one or more tools from your MCP

```bash
mur uninstall TOOL --host HOST
```

- `TOOL`: Name of the tool or toolkit to uninstall e.g. [get_weather](https://artifacts.murmur.nexus/ewg/get_weather)
- `HOST`: Host URL from where you want to uninstall e.g. `http://localhost:8000`

### `mur list`

List installed tools on your MCP

```bash
mur list --host HOST
```

- `HOST`: Host URL from where you want to list tools e.g. `http://localhost:8000`

### `mur config set`

Set a configuration for host.

```bash
mur config set public host HOST
```

- `HOST`: Host URL from where you want to install e.g. `http://localhost:8000`

This allows you to (un)install and list tools without having to specify the host every time. E.g. `mur install TOOL --host` will point to the configured HOST value. Not specifying a host will install the tool in your local python environment under the [murmur](https://github.com/murmur-nexus/murmur) namespace. 


## 🚀 Community

`mur` is in its early stages, and we're actively building it with the developer community in mind. Your insights, ideas, and use cases will help shape its future. First time contributors are welcome! Check out the [GitHub issues](https://github.com/murmur-nexus/mur/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) for some ideas.

---

**Feedback**  
Try `mur`, and let us know what you think. Star this repo 🌟 and join our [Discord community 💬](https://discord.gg/RGKCfD8HhC) to share your feedback and help make tooling for agents accessible for everyone.

