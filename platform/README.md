# SaveVido Central Platform

This folder is an additive foundation for the SaveVido website, release metadata, updater, and truthful analytics. Existing application files are intentionally left untouched.

## Goals

- Keep the existing SaveVido downloader UI and visual language as the reference for the public website.
- Publish Windows and Android releases from one versioned release process.
- Let desktop/mobile clients read a signed, versioned update manifest.
- Report real download and active-session metrics; never display fabricated counters.
- Keep advertising disabled in the new platform until explicitly enabled later.

## Release flow

1. Changes are pushed to the private source repository.
2. CI runs syntax, dependency, packaging, and smoke tests.
3. A release is published only after the required platform artifacts exist and tests pass.
4. The website reads release metadata and links to the published artifacts.
5. Apps check the update manifest. Windows may download and launch a verified installer; Android must follow Android's user-confirmation/install rules.

A normal source push should not silently publish an untested release. Use a version tag or an explicitly approved release workflow.

## Update manifest contract

The machine-readable manifest will contain:
- monotonically increasing release version and release date;
- minimum supported app version;
- platform-specific artifact URLs and SHA-256 checksums;
- human-readable release notes;
- optional mandatory-update flag and minimum supported OS.

Clients must verify the checksum and, for Windows, the publisher signature before installing. A checksum alone proves file integrity, not publisher identity.

## Live analytics

The dashboard must be backed by server-side events:
- downloads increment only after the artifact endpoint successfully serves a file;
- active users are short-lived, privacy-conscious sessions, not a count of installed devices;
- ratings are submitted by users and protected against basic duplicate/spam submissions;
- charts use timestamped database records and clearly label their time window.

Do not expose personal data, raw IP addresses, download URLs, or private repository details in public analytics.

## Deployment notes

The repository currently contains a Flask application and a Vercel rewrite. The Android native packaging project and a production update/analytics service still need to be established and tested. GitHub Pages, Vercel, and Microsoft Store have different hosting and distribution constraints; the release pipeline must be configured for the chosen destinations.

## Non-destructive rule

Do not replace or reformat the existing downloader templates, CSS, JavaScript, Flask routes, or extraction logic as part of this foundation. New platform functionality belongs in new files or isolated modules. Any future integration into existing files must be reviewed separately before it is merged.


## Analytics API (deployed)

- `POST /api/track` records anonymous website page views and refreshes a short-lived session heartbeat. It accepts only `page_view` and `app_open`; it does not accept client-submitted download-success events.
- `GET /api/metrics` returns verified download deliveries, active anonymous sessions (last 5 minutes), verified ratings, and the last 14 days of downloads.
- Vercel stores `DATABASE_URL` as an encrypted environment variable. The browser never receives database credentials.
- Session identifiers are random browser-local IDs; only SHA-256 hashes are stored. Raw IP addresses and personal profile information are not collected.
- Successful downloads remain at zero until a real artifact-serving route records the completed file response. A button click is not counted as a download.
- Ratings remain empty until a rating submission flow with abuse controls is implemented.
