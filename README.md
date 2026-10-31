# HeetKit

A configurable Twitch bot for interactive chat, with AI personalities, custom commands
and a private control panel. Run it on **Windows Desktop** or as **HeetKit Server**
on Linux/Docker. Both use the same bot core and settings model.

AI is optional. Ordinary Twitch commands work without a provider key.
HeetKit is not affiliated with or endorsed by Twitch.

![HeetKit desktop interface](docs/assets/heetkit-main.png)

## Features

- **AI chat:** Gemini, DeepSeek or OpenAI; saved primary/fallback models, supported
  thinking/search controls, personalities, shared instructions and response languages.
- **AI Playground on both hosts:** test the applied setup without posting to Twitch.
  Requests use real provider quota; Playground never uses viewer memory.
- **Commands:** built-ins, aliases, custom single/random/burst replies, permissions,
  cooldowns, timed announcements and a local filter tester.
- **Private access controls:** per-user command restrictions, global AI blocks and
  profile-wide storage opt-outs. These do not ban or timeout Twitch accounts.
- **Channel-scoped history:** last-seen records and optional AI memory, with configurable
  stored/context counts and automatic expiry.
- **Analytics:** private daily trends, command/provider outcomes, coverage and known
  usage estimates. Missing data is shown as unknown; estimates are not invoices.
- **Desktop or Server:** Windows window/tray controls, or private browser management
  with saved channels and Manual, Always On, Stream Only or Disabled operation.
- **Separate profiles and portable configuration:** move settings between hosts while
  keeping credentials, private history and access restrictions separate.

This page describes current source capabilities. Packaged releases may contain an
older feature set; check the notes for the version you download.

## Download

### Windows

**[Latest Windows release](https://github.com/heeetz/heetkit-bot/releases/latest)** ·
[All releases](https://github.com/heeetz/heetkit-bot/releases)

Windows 10/11 x64: choose the installer or portable ZIP.
For Linux AMD64/ARM64, follow the [Docker guide](docs/docker.md).
Server management must remain private, for example over Tailscale or an SSH tunnel.

## Getting started

1. Install HeetKit or extract the portable ZIP.
2. In **Settings > Twitch connection**, enter the Twitch application, bot account
   and target channel details. Save the client secret separately; restart Desktop
   when prompted. Follow [Twitch setup](docs/twitch-setup.md) for registration and consent.
3. Start/connect the bot and authorize the configured bot account. Wait for
   **Connected**: a running process alone does not prove chat is ready.
4. Optionally open **AI > AI setup**, connect a provider key, choose a model and save.
5. Configure Commands, filters and announcements. Use Playground for a provider test
   without posting a chat message.

## Documentation

| I want to… | Guide |
| --- | --- |
| Connect Twitch or change channels | [Twitch setup](docs/twitch-setup.md) |
| Configure AI, memory or Playground | [AI setup](docs/ai-setup.md) |
| Edit commands, announcements and restrictions | [Commands](docs/commands.md) |
| Understand stored data, opt-outs and backups | [Data and privacy](docs/data-and-privacy.md) |
| Run a private Linux server | [Docker](docs/docker.md) |
| Configure browser access or use the API | [Private management](docs/management-api.md) |
| Work on the source | [Development](docs/development.md) |
| Build or publish a release | [Release process](docs/release-process.md) |

## About

Created by **heeetz** · Twitch: [@heet_ok](https://www.twitch.tv/heet_ok) · Discord: `de.tected`.

[Issues and feature requests](https://github.com/heeetz/heetkit-bot/issues) ·
[Security reporting](SECURITY.md) · [Contributing](CONTRIBUTING.md).

[Apache License 2.0](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md).
