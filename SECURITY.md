# Security

Please report suspected vulnerabilities privately. Do not open a public issue or
pull request containing exploit details, credentials, tokens, or private profiles.

Use [GitHub private vulnerability reporting](https://github.com/heeetz/twitch-bot/security/advisories/new)
when available. If GitHub does not offer that option, contact maintainer **heeetz**
privately on Discord at **de.tected**. Send a short description first; agree on a
private way to share sensitive details. Never send working credentials.

Include the affected version or commit, operating system, reproduction steps,
and likely impact using synthetic data. The latest `main` source is supported;
there are currently no supported standalone releases. Response times are best effort.
Coordinate disclosure with the maintainer so a fix can be prepared before publication.

## Credentials and private data

Gemini keys and Twitch client secrets are stored in the OS keyring when configured
through Settings. Private deployment `.env` fallbacks are also supported. Twitch OAuth
tokens, settings, recovery copies, and SQLite activity/conversation data live in the
selected profile. Do not attach these files to issues or source archives. Redact logs
and screenshots before sharing; local filesystem protection depends on your OS account.

If a real credential enters Git history, logs, or a shared archive, revoke/rotate it
at the provider even if the file is later deleted. Removing a file from the current
tree does not remove older copies from Git history, forks, or clones.

Gemini is optional. Enabled AI requests send chat prompts, configured personality
instructions, and recent conversation context when memory is enabled to Google.
Search grounding can involve Google Search. Provider Test and model discovery also
contact Google. See the [README privacy note](README.md#runtime-data-and-privacy).

## Scope

Security reports are welcome for credential/OAuth exposure, arbitrary code execution,
unsafe user input, permission bypasses, and unintended disclosure of chat, user or
configuration data. Also report insecure update/installer behavior and unsafe
interactions with Twitch, AI providers or local storage.

Use public Issues for general bugs and feature requests; use the private reporting
channels above for suspected vulnerabilities.
