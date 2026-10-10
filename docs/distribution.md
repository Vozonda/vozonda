# Distribution: who can listen

Each show answers one question: who can listen to it? There are three levels.

| Level | Feed | Who can listen | What you need |
|-------|------|----------------|---------------|
| Only in Vozonda | none | you, in the web UI | nothing |
| My podcast app | private (link with the feed key) | whoever has the link | your devices reach the address (a VPN such as Tailscale, or the LAN) |
| Public | open, and/or on Nostr | anyone | see the two channels below |

A public show has two channels, at least one of them on:

- **RSS feed:** Apple Podcasts, Spotify and every podcast app. Needs an address on the internet. Apple and
  Spotify fetch feeds from their own servers, so an address that only your own devices reach (127.0.0.1, a
  Tailscale or LAN name) does not work for them.
- **Nostr:** no server of your own. Episodes go to Nostr relays, the audio to Blossom servers, signed with the
  show's own key. Mainstream podcast apps (Apple, Spotify, Fountain, AntennaPod) read RSS, not these events;
  in Nostr clients the episodes appear as posts with audio. The default show has no Nostr key.

## Private vs public, per show

- `show.<n>.public` / `show.default.public` (`1` public, `0` private). A new show starts private; making it
  public is a choice. A show from before this switch (no own value) follows the old global `feed.public`
  (unset means private), so existing installs keep their behaviour.
- `show.<n>.rss` / `show.default.rss`: the show has a feed at all (`0` = only in Vozonda).
- `show.<n>.nostr`: Nostr publishing (public by nature).

A private feed answers only with the feed key (404 without, so the feed's existence is not revealed); from
another device, so do its episodes' audio, transcripts and share pages (on 127.0.0.1 the web UI plays them). The links inside a feed opened with the key carry it, so a
podcast app plays every episode. A public show's feed and media are open.

**The master feed `/feed.xml`:** without the key it lists only episodes of public shows (404 when there is
none); with the key it lists every show that has a feed. An episode belongs to its show by `show_slug`, else by
its show name, else by its watchlist's show (digests); an episode of a deleted show follows the default show.
A watchlist's own feed follows the watchlist's show the same way.

**New link:** `POST /feed/key/rotate` makes a new feed key. Every old link stops working, also in podcast apps
that subscribed with it. Use it when a link reached the wrong person.

## The address other devices use

Feed, share and webhook links are built from one address:

1. the setting `address.public` (set in the web UI; only a plain `http(s)://host[:port]` address),
2. else `VOZONDA_PUBLIC_URL` from `.env`,
3. else the address the request came in on.

`GET /distribution` reports it as `address`: `url`, `source` (`setting`, `env`, `none`), `scope` and
`answers`. The scope is read from the address itself, which is reliable; whether a phone or Apple can reach it
cannot be tested from the server:

| scope | meaning | addresses |
|-------|---------|-----------|
| `this-computer` | only this machine | 127.0.0.1, ::1, localhost |
| `private-network` | your own devices on a VPN or LAN | `*.ts.net`, `*.local`, `*.lan`, `*.home.arpa`, 100.64.0.0/10, 10/8, 172.16/12, 192.168/16, fc00::/7 |
| `internet` | anyone, including Apple and Spotify | everything else |

`answers` is `true` when `<address>/health` returned 200 within 5 s (checked only for an address that was set
and is not this computer), `false` when not, `null` when there is nothing to check. The older fields
`public_url` and `reachable` stay for existing clients.

**On your phone, privately:** reach Vozonda over a VPN (Tailscale, WireGuard), set the address to that name
(for example `http://<machine>.<tailnet>.ts.net:4173`), and use a podcast app that fetches on the device,
such as AntennaPod. Many apps fetch feeds through their own servers, which then see the link and the titles.

## API

- `GET /distribution`: defaults, `address`, per show `rss`, `public`, `nostr`, `feed_url` (with the key for a
  private show), and `feed_private` (some show's link carries the key)
- `PUT /shows/{slug}/rss` with `{"enabled": bool}`: the show has a feed (write auth)
- `PUT /shows/{slug}/public` with `{"enabled": bool}`: public or private (write auth; `default` or `s<n>`)
- `PUT /shows/{slug}/nostr`: Nostr publishing (write auth; `confirm_public: true` to turn it on)
- `POST /feed/key/rotate`: a new feed key, old links stop (write auth)
- `PUT /settings/address.public` with `{"value": "https://pods.example.org"}`: the address (write auth;
  empty clears it)

Presets for new shows: `distribution.rss_default` (default `1`), `nostr.publish_default` (default `0`).
Re-saving a show never changes its switches; deleting it removes them.

## Apple Podcasts and Spotify

A public show with RSS on can be submitted once: Apple Podcasts Connect
(https://podcastsconnect.apple.com/), Spotify for Creators (https://creators.spotify.com/), Podcast Index
(https://podcastindex.org/podcast/add). The address must be on the internet. Not yet in the feed (follow-up
issue #58): a square cover per show, the owner e-mail the directories send their code to, and the
channel-level explicit tag; until then a submission can be refused.

## Nostr considerations

The default Blossom servers (`https://nostr.download`, `https://blossom.primal.net`,
`https://cdn.nostrcheck.me`) are free third-party services: no guarantee of permanence, they may delete files,
some refuse files over about 30 MB. For important shows run your own Blossom server or use a paid one.

Once an episode is on Nostr relays it is replicated; deletion (NIP-09) is best effort. Treat Nostr publishing
as permanent. If you need guaranteed removal, use RSS only, where you control the feed and the files.

## In the app

Settings, section **04 shows & distribution**. Each show is one card: its name and author (they also go into
every MP3, the player and the share page), for podcast apps its category and description, then its reach.
The feed URL has a copy button (with the key for a private feed); turning Nostr on asks for an explicit
confirmation first, and the show's key can be backed up once (nsec). Below the cards: value for value, the AI
disclosure label, the public address status with links to Apple Podcasts Connect, Spotify for Creators and
Podcast Index, the defaults for new shows, and the relay and Blossom server lists. The plain "who can listen?"
cards, the address field and the QR code follow in the next release (#56).
