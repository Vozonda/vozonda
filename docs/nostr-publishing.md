# Nostr Publishing

Publishes a vozonda episode to Nostr relays and stores audio on Blossom
media servers, so readers on Nostr clients can follow the podcast.

## What gets published

| Item | Nostr kind | Where |
|---|---|---|
| Show metadata (name, author, category) | 10154 | relays |
| Episode (kind:54) with audio URLs | 54 | relays |
| Audio file (Opus / MP3) | Blossom blob (SHA-256) | Blossom servers |
| Transcript (VTT) | Blossom blob | Blossom servers |
| Chapters (JSON) | Blossom blob | Blossom servers |

The episode event references every audio URL via `audio` tags and links the
transcript and chapters with `transcript` / `chapters` tags. A Blossom blob
URL looks like `https://blossom.example.com/<sha256>`.

## Relays and Blossom servers

Relay URLs are read from `nostr.relays` (comma-separated). The default list
contains `wss://relay.damus.io`, `wss://nos.lol`, and `wss://relay.primal.net`.

Blossom server URLs are read from `nostr.blossom_servers`. The default list
contains `https://nostr.download`, `https://blossom.primal.net`, and
`https://cdn.nostrcheck.me`.

You can change these in settings or via the API:

```
PUT /settings/nostr.relays {"value": "wss://relay.damus.io,wss://nos.lol"}
PUT /settings/nostr.blossom_servers {"value": "https://nostr.download"}
```

## Turning publishing on and off

Publishing is controlled per show with the `show.<N>.nostr` setting. The
default preset `nostr.publish_default` is `0` (off). When you create a new
show with `POST /shows`, it inherits that preset; saving an existing show
never overwrites its own switch.

Only shows with `show.<N>.nostr == "1"` get published. The API enforces this
at the publish layer (the orchestrator checks the setting per show).

### Enable / disable via API

```
# Check status (returns enabled, npub, last_event_id)
GET /shows/1/nostr

# Enable with confirmation
PUT /shows/1/nostr
{"enabled": true, "confirm_public": true}

# Disable
PUT /shows/1/nostr
{"enabled": false}
```

Enabling without `confirm_public: true` returns HTTP 422 and a message
explaining that episodes become public and are hard to remove.

### Export the secret key

If you want a backup of the show's Nostr identity:

```
POST /shows/1/nostr/export-nsec
```

Returns `{"nsec": "nsec..."}`. The nsec must never be shared (it is the
private key for the show).

## Deleting published episodes

A published episode on Nostr cannot be taken back entirely, but you can send
a best-effort deletion request:

```
DELETE /jobs/<job_id>/nostr
```

This does two things:

1. Sends a NIP-09 kind:5 deletion event to all relays for every kind:54
   event that was published for the job. The deletion event references the
   original event with an `e` tag.

2. Sends a BUD-02 DELETE (kind:24242 with `t=delete`) to each Blossom server
   that holds an audio blob. If the server responds with 200 or 404, the
   blob is considered removed.

Both steps are best effort: relays may ignore deletion events and Blossom
servers may not implement deletion. The operation is asynchronous; relays
and servers may take minutes to propagate or acknowledge.

You can also retry publishing:

```
POST /jobs/<job_id>/nostr/publish
```

This re-runs the full publish flow (show metadata, audio upload, episode
event). If the show has nostr disabled, the retry does nothing.

## Checking publish status

```
# Per-job Nostr publish record
GET /jobs/<job_id>/nostr

# Returns:
# {
#   "job_id": "abc123",
#   "events": [
#     {"kind": 54, "event_id": "xyz...", "relay_url": "...",
#      "relay_ok": true, "server_url": "...", "server_ok": true},
#     ...
#   ]
# }
```

## Why deletion is best effort

- Nostr relays are independent and may keep events even after a NIP-09
  kind:5 deletion. Deletion events are only visible to clients that
  actively check for them.
- Blossom servers may not implement DELETE, or a server may go offline
  before the deletion reaches it.
- Once an episode event is on public relays with audio URLs, those URLs
  may have been cached or reposted by others.

If you need an episode completely removed from the public Nostr, you must
rely on the kind:5 deletion and hope relays respect it. The only way to
guarantee no future propagation is to never publish in the first place.