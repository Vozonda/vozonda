"""Tests for NIP-57 invoice generation (LNURL + zap request + BOLT11)."""

import json
import urllib.parse

import pytest

from vozonda_api.nostr_zaps import (
    PRESET_AMOUNTS_SATS,
    ZAP_RECEIPT_KIND,
    ZAP_REQUEST_KIND,
    build_lnurl_callback_url,
    build_zap_request,
    encode_nostr_param,
    is_valid_bolt11,
    is_valid_lightning_address,
    is_valid_zap_receipt,
    lightning_address_to_url,
    parse_lightning_address,
    parse_lnurl_callback_response,
    sats_to_msats,
    validate_amount_msats,
    validate_lnurl_pay_params,
    validate_zap_request,
)

# Sample 64-char hex keys (not real, just format-valid)
SENDER = "a" * 64
RECIPIENT = "b" * 64
EVENT_ID = "c" * 64
DUMMY_BOLT11 = "lnbc10n1p3testdummy1pp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypqdpl2pkx2ctnv5sxxmmwwd5kgetjypeh2ursdae8g6twvus8g6rfwvs8qun0dfjkxaq8rkx3yf5tcsyz3d73gafnh3cax9rn449d9p5uxz9ezhhj309d3k2grzj9x43rgn5xnql35a7ms"

# Minimal valid BOLT11-like for shape tests (real invoices are longer but this passes our regex)
VALID_BOLT11 = "lnbc1m1p" + "q" * 120
VALID_BOLT11_AMOUNTLESS = "lnbc1p" + "q" * 120  # lnbc + amount? we use 1p -> amount?
# Use a more realistic amount-encoded invoice: lnbc10n = 10 nano BTC = 1 sat
VALID_BOLT11_10N = "lnbc10n1p" + "q" * 120


def test_lightning_address_to_url():
    assert lightning_address_to_url("alice@example.com") == "https://example.com/.well-known/lnurlp/alice"
    assert lightning_address_to_url("Bob@Example.COM") == "https://example.com/.well-known/lnurlp/Bob"
    assert lightning_address_to_url("a@b.co") == "https://b.co/.well-known/lnurlp/a"
    with pytest.raises(ValueError):
        lightning_address_to_url("not-an-address")
    with pytest.raises(ValueError):
        lightning_address_to_url("missing@dot")
    with pytest.raises(ValueError):
        lightning_address_to_url("@example.com")


def test_parse_lightning_address():
    u, d = parse_lightning_address("zap@getalby.com")
    assert u == "zap" and d == "getalby.com"
    assert is_valid_lightning_address("zap@getalby.com")
    assert not is_valid_lightning_address("zap@")
    assert not is_valid_lightning_address("no-at-sign")


def test_sats_msats_conversion():
    assert sats_to_msats(21) == 21000
    assert sats_to_msats(1000) == 1_000_000
    with pytest.raises(ValueError):
        sats_to_msats(-1)
    assert validate_amount_msats(21000, 1000, 100_000) == 21000
    with pytest.raises(ValueError):
        validate_amount_msats(500, 1000, 100_000)
    with pytest.raises(ValueError):
        validate_amount_msats(200_000, 1000, 100_000)


def test_validate_lnurl_pay_params():
    good = {
        "tag": "payRequest",
        "callback": "https://example.com/.well-known/lnurlp/cb",
        "minSendable": 1000,
        "maxSendable": 10000000,
        "metadata": "[]",
        "allowsNostr": True,
        "nostrPubkey": RECIPIENT,
        "commentAllowed": 300,
    }
    ok, _ = validate_lnurl_pay_params(good)
    assert ok
    bad_tag = dict(good, tag="withdrawRequest")
    assert not validate_lnurl_pay_params(bad_tag)[0]
    bad_cb = dict(good, callback="http://insecure.com/cb")
    assert not validate_lnurl_pay_params(bad_cb)[0]
    bad_range = dict(good, minSendable=5000, maxSendable=1000)
    assert not validate_lnurl_pay_params(bad_range)[0]
    no_nostr = dict(good, allowsNostr=False)
    assert not validate_lnurl_pay_params(no_nostr)[0]
    bad_npub = dict(good, nostrPubkey="not-hex")
    assert not validate_lnurl_pay_params(bad_npub)[0]


def test_build_lnurl_callback_url():
    cb = "https://example.com/callback"
    nostr_json = json.dumps({"kind": 9734, "pubkey": SENDER})
    url = build_lnurl_callback_url(cb, 21000, nostr_json, comment="nice episode", lnurl="lnurl1test")
    parsed = urllib.parse.urlparse(url)
    qs = dict(urllib.parse.parse_qsl(parsed.query))
    assert qs["amount"] == "21000"
    assert qs["comment"] == "nice episode"
    assert qs["lnurl"] == "lnurl1test"
    assert json.loads(qs["nostr"])["kind"] == 9734
    # no comment
    url2 = build_lnurl_callback_url(cb, 1000, nostr_json)
    assert "comment" not in urllib.parse.parse_qsl(urllib.parse.urlparse(url2).query)
    with pytest.raises(ValueError):
        build_lnurl_callback_url("http://insecure.com/cb", 1000, nostr_json)
    with pytest.raises(ValueError):
        build_lnurl_callback_url(cb, 1000, nostr_json, comment="x" * 400)


def test_build_and_validate_zap_request():
    req = build_zap_request(
        sender_pubkey=SENDER,
        recipient_pubkey=RECIPIENT,
        amount_msats=21000,
        relays=["wss://relay.damus.io", "wss://nos.lol"],
        content="love this episode",
        lnurl="lnurl1dummy",
        event_id=EVENT_ID,
    )
    assert req["kind"] == ZAP_REQUEST_KIND
    assert req["content"] == "love this episode"
    assert any(t == ["p", RECIPIENT] for t in req["tags"])
    assert any(t[0] == "amount" and t[1] == "21000" for t in req["tags"])
    assert any(t[0] == "relays" for t in req["tags"])
    assert any(t[0] == "lnurl" for t in req["tags"])
    assert any(t[0] == "e" and t[1] == EVENT_ID for t in req["tags"])
    ok, _ = validate_zap_request(req, expected_recipient=RECIPIENT, expected_amount_msats=21000)
    assert ok
    # wrong recipient fails
    ok2, _ = validate_zap_request(req, expected_recipient=SENDER)
    assert not ok2
    # content too long
    with pytest.raises(ValueError):
        build_zap_request(SENDER, RECIPIENT, 1000, ["wss://relay.damus.io"], content="x" * 400)
    # invalid pubkey
    with pytest.raises(ValueError):
        build_zap_request("not-hex", RECIPIENT, 1000, ["wss://relay.damus.io"])
    # missing relays defaults to DEFAULT_RELAYS
    req2 = build_zap_request(SENDER, RECIPIENT, 1000, [])
    assert any(t[0] == "relays" for t in req2["tags"])


def test_validate_zap_request_missing_tags():
    req = build_zap_request(SENDER, RECIPIENT, 1000, ["wss://relay.damus.io"])
    # remove p tag
    req_no_p = dict(req, tags=[t for t in req["tags"] if t[0] != "p"])
    assert not validate_zap_request(req_no_p)[0]
    # remove relays tag
    req_no_relays = dict(req, tags=[t for t in req["tags"] if t[0] != "relays"])
    assert not validate_zap_request(req_no_relays)[0]
    # wrong kind
    assert not validate_zap_request(dict(req, kind=1))[0]


def test_bolt11_validation():
    assert is_valid_bolt11(VALID_BOLT11)
    assert not is_valid_bolt11("notabolt11")
    assert not is_valid_bolt11("lnbc")  # too short
    assert not is_valid_bolt11("")
    # case insensitive
    assert is_valid_bolt11(VALID_BOLT11.upper())
    # parse callback response
    ok, _msg, pr = parse_lnurl_callback_response({"pr": VALID_BOLT11, "verify": "https://example.com/verify"})
    assert ok and pr == VALID_BOLT11
    ok2, _msg2, pr2 = parse_lnurl_callback_response({"status": "ERROR", "reason": "too low"})
    assert not ok2 and pr2 is None
    ok3, _, _ = parse_lnurl_callback_response({"pr": "bad"})
    assert not ok3
    ok4, _, _ = parse_lnurl_callback_response({"verify": "no pr"})
    assert not ok4


def test_preset_amounts_are_valid():
    assert 21 in PRESET_AMOUNTS_SATS
    assert 1000 in PRESET_AMOUNTS_SATS
    for sats in PRESET_AMOUNTS_SATS:
        msats = sats_to_msats(sats)
        # should be within typical LNURL range
        validate_amount_msats(msats, 1000, 100_000_000)


def test_encode_nostr_param():
    event = {"kind": 9734, "content": "hello world & special=chars"}
    s = json.dumps(event)
    enc = encode_nostr_param(s)
    # must be url-encoded, decode back
    assert urllib.parse.unquote(enc) == s
    assert "&" not in enc or "%26" in enc


def test_zap_receipt_validation():
    receipt = {
        "kind": ZAP_RECEIPT_KIND,
        "content": "",
        "pubkey": RECIPIENT,
        "tags": [
            ["p", RECIPIENT],
            ["bolt11", VALID_BOLT11],
            ["description", json.dumps({"kind": 9734})],
        ],
    }
    ok, _ = is_valid_zap_receipt(receipt)
    assert ok
    bad_kind = dict(receipt, kind=9734)
    assert not is_valid_zap_receipt(bad_kind)[0]
    no_bolt11 = dict(receipt, tags=[["p", RECIPIENT]])
    assert not is_valid_zap_receipt(no_bolt11)[0]
    bad_bolt11 = dict(receipt, tags=[["p", RECIPIENT], ["bolt11", "bad"]])
    assert not is_valid_zap_receipt(bad_bolt11)[0]


def test_zap_invoice_generation_flow():
    """Full NIP-57 invoice generation flow without network (mocked LNURL)."""
    # 1. LN address -> URL
    lnurl_url = lightning_address_to_url("maker@getalby.com")
    assert lnurl_url == "https://getalby.com/.well-known/lnurlp/maker"

    # 2. Mock LNURL pay params (as if fetched)
    params = {
        "tag": "payRequest",
        "callback": "https://getalby.com/lnurlp/maker/callback",
        "minSendable": 1000,
        "maxSendable": 100000000,
        "allowsNostr": True,
        "nostrPubkey": RECIPIENT,
        "commentAllowed": 300,
        "metadata": '[["text/plain", "Pay to maker"]]',
    }
    ok, _ = validate_lnurl_pay_params(params)
    assert ok

    # 3. Build zap request (kind 9734) for 100 sats
    sats = 100
    msats = sats_to_msats(sats)
    validate_amount_msats(msats, params["minSendable"], params["maxSendable"])
    zap_req = build_zap_request(
        sender_pubkey=SENDER,
        recipient_pubkey=params["nostrPubkey"],
        amount_msats=msats,
        relays=["wss://relay.damus.io"],
        content="great episode!",
        lnurl="lnurl1test",
    )
    assert validate_zap_request(zap_req)[0]

    # 4. Build callback URL (would be fetched to get invoice)
    zap_json = json.dumps(zap_req, separators=(",", ":"))
    callback_url = build_lnurl_callback_url(
        params["callback"], msats, zap_json, comment=zap_req["content"], lnurl="lnurl1test"
    )
    parsed = urllib.parse.urlparse(callback_url)
    qs = dict(urllib.parse.parse_qsl(parsed.query))
    assert qs["amount"] == str(msats)
    assert "nostr" in qs
    nostr_decoded = json.loads(qs["nostr"])
    assert nostr_decoded["kind"] == ZAP_REQUEST_KIND

    # 5. Mock callback response -> BOLT11
    mock_response = {"pr": VALID_BOLT11, "verify": params["callback"] + "/verify"}
    ok, _, pr = parse_lnurl_callback_response(mock_response)
    assert ok
    assert is_valid_bolt11(pr)

    # 6. Receipt handling (kind 9735) after payment
    receipt = {
        "kind": ZAP_RECEIPT_KIND,
        "tags": [["bolt11", pr], ["p", RECIPIENT], ["description", zap_json]],
        "content": "",
        "pubkey": RECIPIENT,
    }
    assert is_valid_zap_receipt(receipt)[0]


def test_zap_request_content_with_comment():
    # NIP-57: zap request content is the comment from user
    comment = "Zap for the vozonda episode, love the voices"
    req = build_zap_request(SENDER, RECIPIENT, sats_to_msats(500), ["wss://relay.damus.io"], content=comment)
    assert req["content"] == comment
    # empty comment is allowed
    req2 = build_zap_request(SENDER, RECIPIENT, sats_to_msats(21), ["wss://relay.damus.io"], content="")
    assert req2["content"] == ""
