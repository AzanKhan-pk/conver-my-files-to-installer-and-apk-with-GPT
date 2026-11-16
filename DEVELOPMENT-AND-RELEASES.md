# SaveVido release, update and local development

## One source of truth

The `savevido-central-platform` branch is the shared source for the Windows app, Android client, website and release configuration. Changes committed to this branch are available to the VS Code checkout after syncing:

```powershell
git switch savevido-central-platform
git pull --ff-only origin savevido-central-platform
```

Before editing locally, pull first. After editing, run the relevant tests, then commit and push to this same branch. Do not work on a second copy or overwrite another project.

## Release configuration

The public platform reads `platform/release-config.json`. Keep this file as the central version/status record for Windows, Android and Microsoft Store packages. A release channel must not receive a public download URL until its package exists, its SHA-256 is calculated, and the package has passed installation/runtime checks.

The current Windows CI creates an installer artifact. Its successful compile is not the same as a verified installation. Android remains a separate native-client build; do not publish a WebView-only placeholder as a downloader APK. Microsoft Store distribution requires a signed MSIX, a Partner Center listing and certification.

## Update design

- Windows: app checks the central release configuration, compares semantic versions, downloads only a published installer, verifies SHA-256 and asks the user before launching the installer. A signed installer is required for a trustworthy production update flow.
- Android: check the central version record and send users to the official APK/Play Store page; Android must retain the user's install confirmation unless distributed through managed Play Store updates.
- Microsoft Store: use Store-managed updates after submission and approval.

Never place signing keys, API secrets, database credentials or ad-network secrets in source control.

## Ads

Ads are disabled by default. Keep ad configuration centralized and separate from downloader functionality. Do not add intrusive pop-ups, deceptive download buttons or ads that obscure controls. Enable ads only after selecting an approved provider, reviewing its age/audience rules, publishing accurate privacy disclosures and configuring consent where required.

## Safety and rights

Only support lawful public media that the user has permission to save. Private, paywalled, DRM-protected and adult-content sources are not supported. Do not add bypasses for access controls.
