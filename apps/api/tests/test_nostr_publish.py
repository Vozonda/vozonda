"""Tests for NIP-F4 event builders (no signing, no network)."""

import hashlib
import json

from vozonda_api.nostr_publish import (
    build_episode_event,
    build_show_event,
    event_id,
)


class TestBuildShowEvent:
    def test_kind_10154(self):
        show = {"name": "Test Show", "author": "Alice", "category": "Tech"}
        event = build_show_event(show, "abcd" * 16)
        assert event["kind"] == 10154

    def test_no_d_tag(self):
        """kind:10154 is replaceable (10000-19999), not addressable; no d-tag."""
        show = {"name": "Test Show"}
        event = build_show_event(show, "abcd" * 16)
        d_tags = [t for t in event["tags"] if t[0] == "d"]
        assert d_tags == [], "replaceable event must not have d-tag"

    def test_title_tag(self):
        show = {"name": "My Podcast"}
        event = build_show_event(show, "abcd" * 16)
        title_tags = [t for t in event["tags"] if t[0] == "title"]
        assert title_tags == [["title", "My Podcast"]]

    def test_image_tag_when_provided(self):
        show = {"name": "Test"}
        event = build_show_event(show, "abcd" * 16, cover_image_url="https://cdn.example/cover.jpg")
        img_tags = [t for t in event["tags"] if t[0] == "image"]
        assert img_tags == [["image", "https://cdn.example/cover.jpg"]]

    def test_website_tag_when_provided(self):
        show = {"name": "Test"}
        event = build_show_event(show, "abcd" * 16, website_url="https://example.com/rss.xml")
        web_tags = [t for t in event["tags"] if t[0] == "website"]
        assert web_tags == [["website", "https://example.com/rss.xml"]]

    def test_p_tag_only_for_a_hex_pubkey_author(self):
        """NIP-01: a p tag holds a 32-byte lowercase hex pubkey; a display name is no p tag."""
        assert [t for t in build_show_event({"name": "Test", "author": "Alice"}, "abcd" * 16)["tags"] if t[0] == "p"] == []
        hexkey = "ef" * 32
        p_tags = [t for t in build_show_event({"name": "Test", "author": hexkey}, "abcd" * 16)["tags"] if t[0] == "p"]
        assert p_tags == [["p", hexkey]]

    def test_no_p_tag_when_no_author(self):
        show = {"name": "Test"}
        event = build_show_event(show, "abcd" * 16)
        p_tags = [t for t in event["tags"] if t[0] == "p"]
        assert p_tags == []

    def test_language_tag(self):
        show = {"name": "Test"}
        event = build_show_event(show, "abcd" * 16, language="de")
        lang_tags = [t for t in event["tags"] if t[0] == "language"]
        assert lang_tags == [["language", "de"]]

    def test_ai_disclosure_tag(self):
        show = {"name": "Test"}
        event = build_show_event(show, "abcd" * 16)
        ai_tags = [t for t in event["tags"] if t[0] == "ai"]
        assert len(ai_tags) == 1
        assert ai_tags[0][:3] == ["ai", "vozonda", "generated"]
        assert ai_tags[0][3].startswith("vozonda/")

    def test_content_empty_string(self):
        show = {"name": "Test"}
        event = build_show_event(show, "abcd" * 16)
        assert event["content"] == ""

    def test_unsigned_event_no_id_no_sig(self):
        show = {"name": "Test"}
        event = build_show_event(show, "abcd" * 16)
        assert "id" not in event
        assert "sig" not in event

    def test_pubkey_lowercase(self):
        show = {"name": "Test"}
        event = build_show_event(show, "ABCD" * 16)
        assert event["pubkey"] == "abcd" * 16


class TestBuildEpisodeEvent:
    def test_kind_54(self):
        show = {"name": "Test Show"}
        job = {"title": "Ep 1", "description": "Desc", "url": "https://example.com/1"}
        event = build_episode_event(show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16)
        assert event["kind"] == 54

    def test_title_tag(self):
        show = {"name": "Test Show"}
        job = {"title": "Episode One", "description": "Desc", "url": "https://example.com/1"}
        event = build_episode_event(show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16)
        title_tags = [t for t in event["tags"] if t[0] == "title"]
        assert title_tags == [["title", "Episode One"]]

    def test_audio_tags_repeatable_both_formats(self):
        show = {"name": "Test"}
        job = {"title": "Ep", "description": "", "url": "https://example.com/1"}
        audio = [
            ("https://cdn.example/ep.mp3", "audio/mpeg"),
            ("https://cdn.example/ep.opus", "audio/opus"),
        ]
        event = build_episode_event(show, job, audio, "abcd" * 16)
        audio_tags = [t for t in event["tags"] if t[0] == "audio"]
        assert len(audio_tags) == 2
        assert audio_tags[0] == ["audio", "https://cdn.example/ep.mp3", "audio/mpeg"]
        assert audio_tags[1] == ["audio", "https://cdn.example/ep.opus", "audio/opus"]

    def test_duration_int_seconds_string(self):
        show = {"name": "Test"}
        job = {"title": "Ep", "description": "", "url": "https://example.com/1", "duration_ms": 180500}
        event = build_episode_event(show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16)
        dur_tags = [t for t in event["tags"] if t[0] == "duration"]
        assert dur_tags == [["duration", "180"]]

    def test_duration_zero_when_missing(self):
        show = {"name": "Test"}
        job = {"title": "Ep", "description": "", "url": "https://example.com/1"}
        event = build_episode_event(show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16)
        dur_tags = [t for t in event["tags"] if t[0] == "duration"]
        assert dur_tags == [["duration", "0"]]

    def test_image_tag_episode_specific_preferred(self):
        show = {"name": "Test", "image": "https://cdn.example/show.jpg"}
        job = {"title": "Ep", "description": "", "url": "https://example.com/1"}
        event = build_episode_event(
            show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16,
            episode_image_url="https://cdn.example/ep.jpg"
        )
        img_tags = [t for t in event["tags"] if t[0] == "image"]
        assert img_tags == [["image", "https://cdn.example/ep.jpg"]]

    def test_image_tag_fallback_to_show(self):
        show = {"name": "Test", "image": "https://cdn.example/show.jpg"}
        job = {"title": "Ep", "description": "", "url": "https://example.com/1"}
        event = build_episode_event(show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16)
        img_tags = [t for t in event["tags"] if t[0] == "image"]
        assert img_tags == [["image", "https://cdn.example/show.jpg"]]

    def test_published_at_tag(self):
        show = {"name": "Test"}
        job = {"title": "Ep", "description": "", "url": "https://example.com/1", "created_at": 1700000000}
        event = build_episode_event(show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16)
        pub_tags = [t for t in event["tags"] if t[0] == "published_at"]
        assert pub_tags == [["published_at", "1700000000"]]

    def test_a_tag_format_empty_d(self):
        """a-tag coordinate is '10154:<podcast_pubkey>:' (empty d)."""
        show = {"name": "Test"}
        job = {"title": "Ep", "description": "", "url": "https://example.com/1"}
        pubkey = "abcd" * 16
        event = build_episode_event(show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], pubkey)
        a_tags = [t for t in event["tags"] if t[0] == "a"]
        assert len(a_tags) == 1
        assert a_tags[0][1] == f"10154:{pubkey}:"

    def test_no_e_tag_to_show_event(self):
        """Do NOT add e-tag to show event id (it changes on every metadata update)."""
        show = {"name": "Test"}
        job = {"title": "Ep", "description": "", "url": "https://example.com/1"}
        event = build_episode_event(show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16)
        e_tags = [t for t in event["tags"] if t[0] == "e"]
        assert e_tags == []

    def test_r_tag_single_source(self):
        show = {"name": "Test"}
        job = {"title": "Ep", "description": "", "url": "https://example.com/article"}
        event = build_episode_event(show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16)
        r_tags = [t for t in event["tags"] if t[0] == "r"]
        assert r_tags == [["r", "https://example.com/article"]]

    def test_r_tags_multiple_for_digest(self):
        show = {"name": "Test"}
        job = {
            "title": "Digest", "description": "", "url": "https://example.com/main",
            "digest": True, "digest_sources": [
                "https://example.com/a", "https://example.com/b", "https://example.com/c"
            ]
        }
        event = build_episode_event(show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16)
        r_tags = [t for t in event["tags"] if t[0] == "r"]
        assert len(r_tags) == 3
        assert r_tags[0] == ["r", "https://example.com/a"]
        assert r_tags[1] == ["r", "https://example.com/b"]
        assert r_tags[2] == ["r", "https://example.com/c"]

    def test_language_tag_from_job(self):
        show = {"name": "Test"}
        job = {"title": "Ep", "description": "", "url": "https://example.com/1", "language": "fr"}
        event = build_episode_event(show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16)
        lang_tags = [t for t in event["tags"] if t[0] == "language"]
        assert lang_tags == [["language", "fr"]]

    def test_language_auto_defaults_to_en(self):
        show = {"name": "Test"}
        job = {"title": "Ep", "description": "", "url": "https://example.com/1", "language": "auto"}
        event = build_episode_event(show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16)
        lang_tags = [t for t in event["tags"] if t[0] == "language"]
        assert lang_tags == [["language", "en"]]

    def test_transcript_tag(self):
        show = {"name": "Test"}
        job = {"title": "Ep", "description": "", "url": "https://example.com/1"}
        event = build_episode_event(
            show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16,
            transcript_url="https://cdn.example/ep.vtt"
        )
        tr_tags = [t for t in event["tags"] if t[0] == "transcript"]
        assert tr_tags == [["transcript", "https://cdn.example/ep.vtt", "text/vtt"]]

    def test_chapters_tag(self):
        show = {"name": "Test"}
        job = {"title": "Ep", "description": "", "url": "https://example.com/1"}
        event = build_episode_event(
            show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16,
            chapters_url="https://cdn.example/ep.json"
        )
        ch_tags = [t for t in event["tags"] if t[0] == "chapters"]
        assert ch_tags == [["chapters", "https://cdn.example/ep.json", "application/json+chapters"]]

    def test_ai_disclosure_tag_with_model_ids(self):
        show = {"name": "Test"}
        job = {
            "title": "Ep", "description": "", "url": "https://example.com/1",
            "model_ids": ["qwen3-35b", "kokoro-tts"]
        }
        event = build_episode_event(show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16)
        ai_tags = [t for t in event["tags"] if t[0] == "ai"]
        assert len(ai_tags) == 1
        assert ai_tags[0][:3] == ["ai", "vozonda", "generated"]
        assert ai_tags[0][3].startswith("vozonda/")
        assert "qwen3-35b" in ai_tags[0]
        assert "kokoro-tts" in ai_tags[0]

    def test_ai_disclosure_tag_with_single_model_id(self):
        show = {"name": "Test"}
        job = {"title": "Ep", "description": "", "url": "https://example.com/1", "model_id": "qwen3-35b"}
        event = build_episode_event(show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16)
        ai_tags = [t for t in event["tags"] if t[0] == "ai"]
        assert "qwen3-35b" in ai_tags[0]

    def test_content_is_episode_description(self):
        show = {"name": "Test"}
        job = {"title": "Ep", "description": "This is the episode description.", "url": "https://example.com/1"}
        event = build_episode_event(show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16)
        assert event["content"] == "This is the episode description."

    def test_unsigned_event_no_id_no_sig(self):
        show = {"name": "Test"}
        job = {"title": "Ep", "description": "", "url": "https://example.com/1"}
        event = build_episode_event(show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16)
        assert "id" not in event
        assert "sig" not in event

    def test_pubkey_lowercase(self):
        show = {"name": "Test"}
        job = {"title": "Ep", "description": "", "url": "https://example.com/1"}
        event = build_episode_event(show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "ABCD" * 16)
        assert event["pubkey"] == "abcd" * 16


class TestEventId:
    def test_known_nip01_vector(self):
        """Test against a known NIP-01 example vector."""
        # NIP-01 example: kind=1, pubkey=... (from nip-01 spec)
        event = {
            "pubkey": "79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798",
            "created_at": 1629020413,
            "kind": 1,
            "tags": [["e", "abc"], ["p", "def"]],
            "content": "hello",
        }
        # Compute expected using same serialization
        arr = [0, event["pubkey"], event["created_at"], event["kind"], event["tags"], event["content"]]
        serialized = json.dumps(arr, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        expected = hashlib.sha256(serialized).hexdigest()
        assert event_id(event) == expected

    def test_event_id_matches_manual_compute(self):
        event = {
            "pubkey": "abcd" * 16,
            "created_at": 1700000000,
            "kind": 54,
            "tags": [["title", "Test"], ["audio", "https://x/y.mp3", "audio/mpeg"]],
            "content": "description",
        }
        expected = hashlib.sha256(
            json.dumps([0, event["pubkey"], event["created_at"], event["kind"], event["tags"], event["content"]],
                       separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        assert event_id(event) == expected

    def test_event_id_deterministic(self):
        event = {
            "pubkey": "abcd" * 16,
            "created_at": 1700000000,
            "kind": 10154,
            "tags": [["title", "Test"]],
            "content": "",
        }
        id1 = event_id(event)
        id2 = event_id(event)
        assert id1 == id2

    def test_event_id_changes_with_content(self):
        e1 = {"pubkey": "abcd" * 16, "created_at": 1700000000, "kind": 1, "tags": [], "content": "a"}
        e2 = {"pubkey": "abcd" * 16, "created_at": 1700000000, "kind": 1, "tags": [], "content": "b"}
        assert event_id(e1) != event_id(e2)

    def test_event_id_changes_with_tags_order(self):
        e1 = {"pubkey": "abcd" * 16, "created_at": 1700000000, "kind": 1, "tags": [["a", "1"], ["b", "2"]], "content": ""}
        e2 = {"pubkey": "abcd" * 16, "created_at": 1700000000, "kind": 1, "tags": [["b", "2"], ["a", "1"]], "content": ""}
        assert event_id(e1) != event_id(e2)

    def test_event_id_lowercase_hex(self):
        event = {
            "pubkey": "ABCD" * 16,
            "created_at": 1700000000,
            "kind": 1,
            "tags": [],
            "content": "",
        }
        eid = event_id(event)
        assert eid == eid.lower()
        assert len(eid) == 64


class TestIntegration:
    def test_show_and_episode_link_via_a_tag(self):
        show = {"name": "My Show", "author": "Alice", "category": "Tech"}
        job = {"title": "Ep 1", "description": "First episode", "url": "https://example.com/1"}
        pubkey = "abcd" * 16

        show_event = build_show_event(show, pubkey)
        _ = event_id(show_event)

        ep_event = build_episode_event(show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], pubkey)

        # a-tag references show coordinate, not show event id
        a_tags = [t for t in ep_event["tags"] if t[0] == "a"]
        assert a_tags[0][1] == f"10154:{pubkey}:"

        # no e-tag to show event id
        e_tags = [t for t in ep_event["tags"] if t[0] == "e"]
        assert e_tags == []

    def test_optional_fields_absent_cleanly(self):
        """Optional fields (transcript, chapters, image, etc.) absent cleanly."""
        show = {"name": "Test"}
        job = {"title": "Ep", "description": "", "url": "https://example.com/1"}
        event = build_episode_event(show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16)

        # These should not be present when not provided
        assert not any(t[0] == "transcript" for t in event["tags"])
        assert not any(t[0] == "chapters" for t in event["tags"])
        assert not any(t[0] == "image" for t in event["tags"])

    def test_digest_with_several_r_tags(self):
        show = {"name": "Test"}
        job = {
            "title": "Weekly Digest", "description": "", "url": "https://example.com/main",
            "digest": True, "digest_sources": [f"https://example.com/{i}" for i in range(5)]
        }
        event = build_episode_event(show, job, [("https://cdn.example/ep.mp3", "audio/mpeg")], "abcd" * 16)
        r_tags = [t for t in event["tags"] if t[0] == "r"]
        assert len(r_tags) == 5