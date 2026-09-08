# Security

CleanTake handles recordings that may be private. The core processing path is local, with no account or automatic upload.

## Reporting a vulnerability

Report security issues privately to **pavan.gupta.352@gmail.com**. Include the affected version, platform, a minimal reproduction and the impact you observed. Do not include private audio or access tokens. Please avoid posting exploit details publicly before the maintainer has had a chance to investigate.

## Intended boundary

The studio service is designed to bind to loopback and require a session token. It is a single-user local application, not an internet-facing multiuser service. Exposing it through a reverse proxy, port-forward or shared host changes that boundary.

Imported media and project archives are untrusted input. Keep FFmpeg and the application current. Source paths, archive members, uploads and export names must remain within the selected workspace. A filename must never become a shell command.

Original recordings remain on disk until you explicitly delete the project. Exporting a portable project includes its source recordings; choose the recipient and destination accordingly. Logs and issue reports should contain operational information, not transcript contents or private recording paths.

## Supported versions

Security fixes target the latest published release and the main branch. Older development
snapshots should be updated before investigating a report. This is a new project;
there is no guaranteed response time or long-term maintenance contract.
