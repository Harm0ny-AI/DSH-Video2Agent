# Security

## Reporting

Open a private GitHub security advisory. Do not post credentials, cookies, or
private video paths in a public issue.

## Threat model

DSH-Video2Agent is a local CLI. It processes untrusted media and platform URLs, and it
may be driven by an agent that reads untrusted video text.

- URL ingestion can be used for SSRF if exposed as a service. The default is a
  local, user-driven CLI. DSH-Video2Agent preflights the initial http(s) URL and
  rejects private/loopback/link-local/cloud-metadata addresses, but it does not
  re-validate every redirect that yt-dlp follows. Set allow_private_urls=true
  only for trusted local testing. For untrusted multi-tenant use, put the
  downloader behind an egress proxy and authentication.
- Transcripts and OCR are untrusted data. The Skill marks them as content, not
  instructions.
- Local path access is the user's responsibility. Set allowed_roots in
  config.json to restrict local files to specific directories; an empty list
  keeps the CLI unrestricted for compatibility. The DSH plugin does not set a
  root by default; for a shared machine set allowed_roots before exposing the
  plugin to untrusted prompts.
- Bilibili public metadata/download uses anonymous cookies stored under
  VIDEO2AGENT_HOME/cookies. User-provided cookies are stored only locally and are
  never logged.
- No telemetry. Local mode does not upload anything: ASR and OCR run on this
  machine and the video file never leaves it. Cloud ASR/OCR is different: when
  you save an API key and switch a section to the cloud provider, the extracted
  audio (ASR) or the frames it reads (OCR) are sent to the provider you
  configured. The settings page shows that line next to the cloud switch. The
  host model may also receive selected frames/text if it is a cloud model.
- Local paths stay local. Evidence frame links use an opaque
  `<video_id>/<file>` id, never an absolute path; exports redact absolute paths
  to file names by default (`--include-paths` opts out); job logs are pruned by
  `video2agent gc` (default 7 days). Enable none of these if you deliberately want
  the paths in the output.
- Write routes require a JSON body and a loopback `Host`. A foreign `Origin` or
  a non-loopback `Host` is refused. Missing, `null`, `dsh-app://` and `file://`
  origins are accepted **only** for loopback JSON writes, because the desktop
  shell uses a custom scheme; a foreign origin is still 403. A bodyless
  `text/plain` POST is refused (415).

## Secrets

Never commit cookies, API keys, or private video files. Use a local cookies
file outside the repository and keep it readable only by the user.

- **Cloud API key:** on Windows it is encrypted with DPAPI in
  `$VIDEO2AGENT_HOME/secrets/cloud.bin`; on other platforms the key is kept in a
  local file with user-only permissions (no DPAPI). It is never put in
  `ui-settings.json`, argv, logs, or a route response.
- **Bilibili cookies:** the login jar is a plaintext Netscape cookie file under
  `$VIDEO2AGENT_HOME/cookies/`, not DPAPI-encrypted. It is local-only; best-effort
  file permissions are applied, but another process running as the same user can
  read it. Do not sync that directory to a cloud drive.
- **Host model:** `evidence` attaches frames/text to the model request. If the
  host model is cloud-based, those frames leave the machine even when local
  ASR/OCR is selected. The settings page and README state this separately from
  the local ASR/OCR upload switch.
