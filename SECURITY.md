# Security Policy

## Supported Versions

Twitch Bot is currently in active development.

Until the first stable release, security fixes are applied to the latest version of the project only.

| Version | Supported |
| ------- | --------- |
| Latest release / current main | ✅ |
| Older releases | ❌ |

This policy may be updated once stable versioned releases are available.

## Reporting a Vulnerability

Please do **not** report security vulnerabilities through public GitHub Issues or Discussions.

If GitHub Private Vulnerability Reporting is enabled for this repository, use:

**Security → Report a vulnerability**

This is the preferred reporting method.

If private vulnerability reporting is unavailable, contact the maintainer on Discord:

**de.tected**

Please provide:
- a short description of the issue;
- affected version or commit;
- steps to reproduce;
- the potential impact;
- any relevant logs, screenshots, or proof-of-concept details.

Do not include credentials, access tokens, API keys, or other sensitive data unless explicitly requested through a private channel.

I will review reports as soon as reasonably possible and may request additional information before confirming the issue.

If the vulnerability is confirmed, a fix will be prepared before public technical details are disclosed where practical.

## Scope

Security reports are especially welcome for issues involving:

- credential or OAuth token exposure;
- arbitrary code execution;
- unsafe handling of user-controlled input;
- privilege or permission bypasses;
- unintended disclosure of chat, user, or configuration data;
- insecure update or installer behavior;
- unsafe interactions with Twitch, AI providers, or local storage.

General bugs and feature requests should be reported through GitHub Issues instead.
