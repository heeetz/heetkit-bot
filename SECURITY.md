# Security

Please report suspected vulnerabilities privately. Do not open a public issue or
pull request containing exploit details, credentials, tokens, or private profiles.

Use [GitHub private vulnerability reporting](https://github.com/heeetz/heetkit-bot/security/advisories/new)
when available. If GitHub does not offer that option, contact maintainer **heeetz**
privately on Discord at **de.tected**. Send a short description first; agree on a
private way to share sensitive details. Never send working credentials.

Include the affected version or commit, operating system, reproduction steps,
and likely impact using synthetic data. Identify whether the issue affects the latest
`main` source or a published Windows release. Response times are best effort.
Coordinate disclosure with the maintainer so a fix can be prepared before publication.

## Credentials and private data

Gemini keys and Twitch client secrets are stored in the OS keyring when configured
through Settings. Advanced deployments may provide process environment fallbacks; the
application does not discover or load dotenv files. Twitch OAuth tokens, settings, recovery
copies, and SQLite activity/conversation data live in the selected profile. Do not attach
these files or process environment contents to issues or source archives. Redact logs and
screenshots before sharing; local filesystem protection depends on your OS account.

If a real credential enters Git history, logs, or a shared archive, revoke/rotate it
at the provider even if the file is later deleted. Removing a file from the current
tree does not remove older copies from Git history, forks, or clones.

Gemini is optional. Enabled AI requests send chat prompts, configured personality
instructions, and recent conversation context when memory is enabled to Google.
Search grounding can involve Google Search. Provider Test and model discovery also
contact Google. See [data and privacy](docs/data-and-privacy.md#ai-processing-and-memory).

## Dependency security baseline

Source installs require aiohttp 3.14.4+, certifi 2026.10.19+, multidict 6.9.1+
and, for Desktop, Pillow 13.0.0+. Windows and Linux packaging pin the compatible
closure; Linux retains verified wheel hashes for both amd64 and ARM64. The frontend
requires Vite 7.3.7+ within version 7 and uses the committed npm integrity lock.
Canonical builds first install the hash-verified pip 26.2.2 bootstrap from
`packaging/python-bootstrap.txt`, which also corrects pip's separately vendored CA bundle.

aiohttp handles management HTTP and Twitch/provider traffic; certifi supplies CA
trust to HTTP clients. Pillow is required by the desktop tray, which opens the shipped
PNG, and by the source icon generator. Vite is development/build tooling; installed
applications serve its static output. These usage boundaries do not replace updating
vulnerable dependencies. Rebuild existing binaries/images to receive corrected packages;
updating source does not repair previously downloaded releases.

### Package-installer limitation

pip 26.2.2 corrects its CA bundle but still vendors urllib3 2.7.0. The application
uses the separately pinned urllib3 2.8.0; upgrading it cannot replace pip's private copy.
The latest available pip wheel therefore retains
[GHSA-vxq7-64xx-v4gw](https://github.com/advisories/GHSA-vxq7-64xx-v4gw),
[GHSA-gh4c-6fx4-qh6g](https://github.com/advisories/GHSA-gh4c-6fx4-qh6g) and
[GHSA-8988-9cw3-xx77](https://github.com/advisories/GHSA-8988-9cw3-xx77).

The streaming findings require hostile chunked download responses; the proxy finding
requires HTTPS proxy/target TLS-policy interactions. pip disables content decoding for
artifact downloads, avoiding the Deflate streaming path there. Canonical builds use the official
package index with certificate verification, hash-lock the bootstrap and Linux wheels,
and do not configure custom proxy TLS policies. Frozen Windows applications exclude pip;
the container uses it only for offline `pip check`, and the bot never invokes it.
Keep package installation in the controlled build process. As of 2026-10-21, no published
pip distribution includes urllib3 2.8.0; replacing vendored code manually would create
an unsupported installer. These embedded-tool advisories remain unresolved pending
an upstream pip update and must be reassessed when refreshing the bootstrap.

## Scope

Security reports are welcome for credential/OAuth exposure, arbitrary code execution,
unsafe user input, permission bypasses, and unintended disclosure of chat, user or
configuration data. Also report insecure update/installer behavior and unsafe
interactions with Twitch, AI providers or local storage.

Use public Issues for general bugs and feature requests; use the private reporting
channels above for suspected vulnerabilities.
