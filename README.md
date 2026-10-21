# HeetKit

### AI personalities and interactive Twitch chat on Desktop or Server

HeetKit is a configurable Twitch bot focused on entertainment and interactive chat.
Use **Windows Desktop** for a local window and tray controls, or **HeetKit Server**
on Linux/Docker with private browser management.

Its main feature is a customizable Gemini-powered AI responder: create personalities, add profile-wide instructions, choose models, optionally keep conversation memory, and shape how the bot talks in your chat.

HeetKit also includes custom commands, useful chat utilities, permissions, cooldowns, filters, live logs, and a local desktop control panel.

> HeetKit is not affiliated with or endorsed by Twitch.

---

## Screenshot

![HeetKit desktop interface](docs/assets/heetkit-main.png)

---

## Features

- **Configurable AI chat** powered by Gemini
- **Local AI Playground** to test real Gemini replies without posting to Twitch (uses API quota)
- **Custom AI personalities** with editable prompts and shared profile instructions
- **Custom Twitch commands** with aliases, responses, permissions and cooldowns
- **Useful chat commands** such as followage, weather, last seen and uptime
- **Conversation memory** for AI replies
- **Configurable chat and AI filters** with a local tester for active rules and unsaved drafts
- **Desktop control panel** with live logs and tray controls
- **Local profiles** with separate settings and data
- **HeetKit Server** with native AMD64/ARM64 containers, private browser setup,
  saved channels and persistent operation modes
- **Configuration transfer** between Desktop and Server, excluding secrets and history

Gemini is optional. Normal Twitch commands work without an AI API key.

---

## Download

### Windows

Download the latest installer or portable version from:

**[Latest release](https://github.com/heeetz/heetkit-bot/releases/latest)**

You can also browse all available builds on the
**[Releases page](https://github.com/heeetz/heetkit-bot/releases)**.

Windows 10/11 x64 is the primary supported platform.
HeetKit Server runs from source through the [Linux Docker guide](docs/docker.md);
manage it privately through Tailscale or an SSH tunnel.
See the [v1.4.1 changes](docs/releases/v1.4.1.md).

---

## Getting started

1. Install HeetKit or extract the portable build.
2. In Settings, save the Twitch application details, client secret, bot account and target channel, then restart HeetKit.
3. Select **Start Bot** on Dashboard, then **Authorize Twitch** as the configured bot account when prompted.
4. Wait for **Connected**. Session **Running** alone does not mean Twitch chat is connected.
5. Optionally add a Gemini API key to enable AI chat.

New to Twitch applications or Gemini API keys?

- **[Twitch setup guide](docs/twitch-setup.md)**
- **[AI / Gemini setup guide](docs/ai-setup.md)**

For HeetKit's current Twitch connection model, the bot account should have moderator access in the target channel. See the Twitch setup guide for details.

---

## Documentation

- [Twitch setup](docs/twitch-setup.md)
- [AI / Gemini setup](docs/ai-setup.md)
- [Commands and customization](docs/commands.md)
- [Data, profiles and privacy](docs/data-and-privacy.md)
- [Development and building from source](docs/development.md)
- [Linux Docker usage](docs/docker.md)
- [Private Server management](docs/management-api.md)
- [Release process](docs/release-process.md)

For bugs and feature requests, use
[GitHub Issues](https://github.com/heeetz/heetkit-bot/issues).

Security issues should be reported according to [SECURITY.md](SECURITY.md).

---

## About

HeetKit is created and maintained by **heeetz**.

- Twitch: [@heet_ok](https://www.twitch.tv/heet_ok)
- Discord: `de.tected`
- License: [Apache License 2.0](LICENSE)
- Third-party licenses: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).
