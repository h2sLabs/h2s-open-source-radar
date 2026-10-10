# Security Policy

Please report a security issue privately rather than opening a public issue that
contains credentials, personal data, or an exploitable proof-of-concept.

For now, contact the project owner through the GitHub profile associated with
H2S Labs. A dedicated security email will be added once the public support
address for h2sstudio.com is finalized.

## Scope

Security-sensitive areas include local context collection, GitHub API token
handling, LaunchAgent persistence, URL opening, and release packaging.

## Easy Install safety model

The one-click installer is deliberately conservative:

- Install is disabled when current-Mac compatibility is blocked or the release target is ambiguous.
- Automatic downloads are limited to official GitHub Release assets and approved GitHub download hosts.
- ZIP/TAR archives are checked for path traversal; TAR links are rejected.
- Radar does not automatically execute arbitrary `install.sh`, repository scripts, or unverified commands.
- DMG images are mounted read-only and app bundles are copied to the user-selected H2S Tools directory.
- PKG files are handed to Apple's Installer; administrator and Gatekeeper prompts are never bypassed.
- Disk-space checks use a conservative installed-size estimate and keep a safety margin.

Compatibility detection is a best-effort preflight, not a guarantee that third-party software is defect-free or safe. Users should still review the upstream project's reputation and license for sensitive environments.
