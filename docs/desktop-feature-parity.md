# Desktop feature parity audit

This checklist records the legacy Tkinter controls reviewed before its removal.

| Legacy capability | Modern control panel | Result |
| --- | --- | --- |
| Start/stop bot | Dashboard buttons and tray Start/Stop action | Parity confirmed |
| Bot running status | Dashboard status card | Parity confirmed |
| Twitch connection status | Dashboard connection card | Improved |
| Session uptime | Dashboard uptime card | Parity confirmed |
| Enable/disable every registered command, including hidden commands | Registry-driven Commands editor | Improved: includes Apply, Save, and Reset |
| AI enable/disable | AI page runtime toggle | Parity confirmed |
| AI memory enable/disable | AI page runtime toggle | Parity confirmed |
| Active personality selection | AI personality selector and Apply action | Improved: includes editable local overrides, Save, and Reset |
| Stop button / window close shutdown | Dashboard Stop, tray Exit, and normal window close | Parity confirmed through the shared orderly lifecycle |

No intentional legacy control was dropped as obsolete. The modern UI additionally provides
command permissions/cooldowns, personality overrides, live logs, desktop settings, and tray
behavior. Tkinter maintained no backend-only capability after this audit.
