"""Gate for VOZONDA-REACH-UI-ADDRESS: text checks on the web sources.

No server, no GPU, no network: reads the Svelte/TS sources as text.
"""

from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "lib"
ADDRESS_CARD = WEB / "components" / "AddressCard.svelte"
SETTINGS = WEB / "components" / "SettingsScreen.svelte"
API = WEB / "api.ts"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_address_card_saves_via_saveSetting_and_has_origin_button():
    text = _read(ADDRESS_CARD)
    assert "saveSetting('address.public'" in text, "AddressCard must save via saveSetting('address.public')"
    assert "use the address you are on now" in text, "'use the address you are on now' missing in AddressCard.svelte"
    assert "location.origin" in text, "location.origin missing in AddressCard.svelte"


def test_address_card_has_scope_texts():
    text = _read(ADDRESS_CARD)
    assert "only this computer reaches it: your phone and apps cannot" in text
    assert "only your own devices on your network or vpn reach it (tailscale, lan): fine for your phone, not for apple or spotify" in text
    assert "anyone on the internet can reach it" in text


def test_address_card_has_answers_line():
    text = _read(ADDRESS_CARD)
    assert "answers" in text, "answers text missing in AddressCard.svelte"
    assert "does not answer from this server" in text


def test_address_card_has_env_note():
    text = _read(ADDRESS_CARD)
    assert "set in .env as VOZONDA_PUBLIC_URL" in text


def test_api_exports_setShowPublic_and_rotateFeedKey():
    text = _read(API)
    assert "export async function setShowPublic" in text, "setShowPublic missing in api.ts"
    assert "export async function rotateFeedKey" in text, "rotateFeedKey missing in api.ts"
    assert "/shows/${encodeURIComponent(slug)}/public" in text, "setShowPublic endpoint missing"
    assert "/feed/key/rotate" in text, "rotateFeedKey endpoint missing"


def test_api_distribution_meta_has_address():
    text = _read(API)
    assert "address: DistributionAddress" in text or "address:{" in text, "DistributionMeta must have 'address' field in api.ts"
    assert "url: string" in text, "DistributionAddress.url missing in api.ts"
    assert "source: 'setting' | 'env' | 'none'" in text, "DistributionAddress.source missing in api.ts"
    assert "answers: boolean | null" in text, "DistributionAddress.answers missing in api.ts"


def test_settings_screen_mounts_address_card_and_no_reachable_outside():
    text = _read(SETTINGS)
    assert "AddressCard" in text, "SettingsScreen must import AddressCard"
    assert "<AddressCard" in text, "SettingsScreen must render <AddressCard"
    assert "reachable from outside" not in text, "SettingsScreen must no longer contain 'reachable from outside'"


def test_address_card_mentions_env_var():
    text = _read(ADDRESS_CARD)
    assert "VOZONDA_PUBLIC_URL" in text, "AddressCard must mention VOZONDA_PUBLIC_URL env var"

def test_save_setting_reports_a_refused_value():
    """saveSetting threw nothing on a 422, so a refused address (or any refused setting) looked saved."""
    text = _read(API)
    body = text[text.index("export async function saveSetting"):]
    body = body[:body.index("\n}\n")]
    assert "if (!res.ok)" in body and "throw new Error" in body


def test_settings_show_a_refused_value_instead_of_saved():
    text = _read(SETTINGS)
    assert "saveError" in text and "not saved:" in text


def test_address_input_is_empty_when_no_address_is_set():
    text = _read(ADDRESS_CARD)
    assert "a.source === 'none' ? '' : a.url" in text
