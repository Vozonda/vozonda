# Distribution

Each show in vozonda chooses its own reach: where its episodes can be found. There are four options:

| Reach | RSS feed | Nostr | What you need |
|-------|----------|-------|---------------|
| Private | no | no | nothing |
| Podcast apps | yes | no | public address (`VOZONDA_PUBLIC_URL`) |
| Nostr only | no | yes | nothing |
| Both | yes | yes | public address |

## The four reaches

### Private
The show has no public feed and does not publish to Nostr. Episodes are only accessible through the web UI or direct links you share. Use this for drafts, internal podcasts, or shows you are not ready to distribute.

### Podcast apps (RSS only)
The show has an RSS feed at `/{creator}/{show}/feed.xml` and appears in the master `/feed.xml`. Any podcast app (Apple Podcasts, Spotify, Pocket Casts, AntennaPod, etc.) can subscribe.

**Requirement:** your vozonda instance must be reachable at a public address. Set `VOZONDA_PUBLIC_URL` to the full public URL (e.g. `https://podcast.example.com`). The server checks reachability by requesting `VOZONDA_PUBLIC_URL/health` with a 5 s timeout.

Without a public address, podcast apps cannot fetch the feed or the audio files.

### Nostr only
The show publishes each episode as a Nostr event (kind 54 + kind 21 for the audio blob). No RSS feed is created. The show does not appear in the master `/feed.xml`.

**Requirement:** none. Nostr relays and Blossom servers are configured globally (`nostr.relays`, `nostr.blossom_servers`). The show's Nostr switch (`show.<n>.nostr`) must be on.

### Both (RSS + Nostr)
The show has an RSS feed and also publishes to Nostr. Maximum reach.

## Configuration

### Per-show switches
Each show has two independent switches:

- `show.<n>.rss` - enables the RSS feed (`1` = on, `0` = off)
- `show.<n>.nostr` - enables Nostr publishing (`1` = on, `0` = off)

A new show starts with the global presets:
- `distribution.rss_default` (default `1`)
- `nostr.publish_default` (default `0`)

Re-saving an existing show never changes its switches. Deleting a show removes both switches.

### API
- `GET /distribution` - returns defaults, public URL reachability, and per-show reach
- `PUT /shows/{slug}/rss` - toggle RSS for a show (write auth required)
- `PUT /shows/{slug}/nostr` - toggle Nostr for a show (write auth required, requires `confirm_public: true` to enable)

### Defaults
- `distribution.rss_default` - preset for new shows (default `1`)
- `nostr.publish_default` - preset for new shows (default `0`)

Change these in settings before creating shows, or toggle per show after creation.

## Directory submission (RSS shows only)

If a show has RSS enabled, you can submit its feed to podcast directories. The feed URL is:
```
{VOZONDA_PUBLIC_URL}/{creator}/{show}/feed.xml
```

Static submission links (no API calls):

- Apple Podcasts Connect: https://podcastsconnect.apple.com/
- Spotify for Creators: https://creators.spotify.com/
- Podcast Index: https://podcastindex.org/podcast/add

## Nostr considerations

### Free Blossom servers
The default Blossom servers (`https://nostr.download`, `https://blossom.primal.net`, `https://cdn.nostrcheck.me`) are free third-party services. They:
- Keep audio files without a guarantee of permanence
- May delete files at any time
- Have size limits (some refuse files over ~30 MB, roughly half an hour of audio)

For important shows, run your own Blossom server or use a paid provider.

### Nostr posts are hard to remove
Once an episode is published to Nostr relays, it is replicated across the network. Deletion (NIP-09) is best-effort:
- Relays may not honor deletion requests
- Blossom servers may not delete the audio blob
- Clients may have cached the event

Treat Nostr publishing as permanent. If you need guaranteed removal, use RSS only (where you control the feed and files).

## Reachability check

`GET /distribution` reports whether your public URL is reachable:
- `reachable: true` - `VOZONDA_PUBLIC_URL/health` returned 200 OK within 5 s
- `reachable: false` - the request failed or returned non-200
- `reachable: null` - no `VOZONDA_PUBLIC_URL` is set

If reachable is `false`, podcast apps will not be able to fetch your RSS feed or audio files. Fix your public URL or network configuration.

## Examples

### Private show
```json
{ "rss": "0", "nostr": "0" }
```
No public presence. Episodes only in the web UI.

### Podcast apps only
```json
{ "rss": "1", "nostr": "0" }
```
RSS feed at `/{creator}/{show}/feed.xml`. Appears in master `/feed.xml`. Requires `VOZONDA_PUBLIC_URL`.

### Nostr only
```json
{ "rss": "0", "nostr": "1" }
```
No RSS feed. Publishes to Nostr relays. No public URL needed.

### Both
```json
{ "rss": "1", "nostr": "1" }
```
Maximum distribution. RSS feed + Nostr publishing. Requires `VOZONDA_PUBLIC_URL`.
## In the app

Settings, section **04 shows & distribution**. Each show is one card: its name and author
(they also go into every MP3, the player and the share page), for podcast apps its category
and description, then its reach. The feed URL has a copy button; turning Nostr on asks for an
explicit confirmation first, and the show's key can be backed up once (nsec). Below the cards:
value for value, the AI disclosure label, the public address status with links to Apple
Podcasts Connect, Spotify for Creators and Podcast Index, the defaults for new shows, and the
relay and Blossom server lists (one per line).

Two rules worth knowing:

- A show created before the RSS switch existed keeps its feed (an unset switch means on; only
  an explicit "off" removes the feed).
- Show numbers are never reused. A deleted show keeps its key file (its Nostr identity), so a
  new show always gets a number no show had before.

## Watchlists

A watchlist can publish into a numbered show (`show_slug`): its episodes inherit the show's
reach (rss, nostr) from settings section 04 shows, including the per-watchlist feed 404 when
the show's RSS is off. Empty keeps the standalone feed behaviour.
