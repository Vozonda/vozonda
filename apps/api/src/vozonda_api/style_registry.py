"""Style registry: single source of truth for every style.

All style data is defined as module-level constants and then consolidated into
the REGISTRY tuple of frozen Style dataclass instances. Derived read-only views
are re-exported from the registry for backwards compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .rhythm import Profile


def get_setting_safe(key: str) -> str | None:
    """Safely get a setting value, returning None on any error."""
    try:
        from .settings_store import get_setting

        return get_setting(key)
    except Exception:
        return None

# ---- Emotion register catalogue (from styles.py) ----
EMOTION_IDS = [
    "neutral", "warm", "calm", "energetic", "dramatic", "cheerful", "serious",
    "true_crime", "tech_roast",
]

EMOTION_DOCS: dict[str, str] = {
    "neutral": "Natural conversational baseline",
    "warm": "Friendly and inviting, like good news with friends",
    "calm": "Measured and relaxed documentary style",
    "energetic": "High pace and infectious enthusiasm",
    "dramatic": "Weighted, tense and high stakes",
    "cheerful": "Bright, uplifting and lighthearted",
    "serious": "Grounded, precise and sober",
    "true_crime": "Atmospheric tension, deep suspense, dramatic pauses.",
    "tech_roast": "Sharp witty debate, fast paced banter, sarcastic tone.",
}

EMOTION_INSTRUCTS: dict[str, str] = {
    "neutral": "",
    "warm": "Speak warmly and invitingly, like sharing good news with friends.",
    "calm": "Speak calmly and measured, documentary narration style.",
    "energetic": "Speak energetically with infectious enthusiasm.",
    "dramatic": "Speak dramatically with weight and tension.",
    "cheerful": "Speak cheerfully and bright.",
    "serious": "Speak seriously and gravely.",
    "true_crime": "Speak with atmospheric tension, deep suspense, and dramatic pauses.",
    "tech_roast": "Speak with sharp wit, fast-paced banter, and a sarcastic tone.",
}


@dataclass(frozen=True)
class Style:
    """Complete style definition."""
    id: str
    doc: str
    group: str  # 'learn' | 'mood' | 'drama' | 'play'
    icon: str
    hook_brief: str
    script_params: dict[str, Any]
    template: str
    profile: Profile
    speaker_instructs: dict[str, str]
    hosts: str  # e.g. "AB" or "ABC"


# ---- Style group and icon mappings (from apps/web/src/App.svelte) ----
_STYLE_GROUP_MAP: dict[str, str] = {
    "balanced": "learn", "eli5": "learn", "serious": "learn", "socrates": "learn",
    "asmr": "mood", "meditation": "mood", "slang": "mood", "noir": "mood",
    "sensational": "drama", "storyteller": "drama", "debate": "drama", "courtroom": "drama",
    "clash": "drama", "conspiracy": "drama", "true_crime": "drama", "crisis_room": "drama",
    "futbol": "play", "dude": "play", "tech_roast": "play", "trivia": "play",
}

_STYLE_ICON_MAP: dict[str, str] = {
    "balanced": "balanced", "eli5": "eli5", "serious": "serious", "socrates": "socrates",
    "asmr": "asmr", "meditation": "meditation", "slang": "slang", "noir": "storyteller",
    "sensational": "sensational", "storyteller": "storyteller",
    "debate": "debate", "clash": "clash", "conspiracy": "conspiracy", "true_crime": "storyteller",
    "courtroom": "balanced", "crisis_room": "pulse",
    "futbol": "futbol", "dude": "dude", "tech_roast": "witty", "trivia": "witty",
}


# ---- Canonical style order (energy axis: whisper -> shout, from styles.py) ----
STYLE_IDS: list[str] = [
    "asmr", "meditation", "eli5", "balanced",
    "storyteller", "serious", "slang",
    "sensational", "debate", "clash", "conspiracy", "futbol",
    "socrates", "dude",
    "true_crime", "tech_roast",
    "noir", "trivia", "courtroom", "crisis_room",
]

# Legacy alias
STYLES: list[str] = STYLE_IDS


# ---- Style docs (from styles.py) ----
STYLE_DOCS: dict[str, str] = {
    "balanced": "Balanced tour: curious host, expert guest.",
    "serious": "Precise and evidence-first, no jokes.",
    "sensational": "High energy and stakes, zero fabrication.",
    "eli5": "A five-year-old gets it wrong in creative ways; B fixes the picture, not the kid.",
    "slang": "Two friends after hours in the casual register of your language. Cool, not cringe.",
    "debate": "Sharp pro/contra from the same source; ends in shared ground.",
    "storyteller": "Three named chapters, cliffhanger cuts; B lives inside the story.",
    "clash": "A heated on-air fight over ideas: interruptions, challenges, no fake peace at the end.",
    "asmr": "Whisper session: max twelve words per turn; the silences carry it.",
    "meditation": "Gentle ASMR soothing narration, slow tempo and guided presence.",
    "futbol": "Latin American football-commentator energy: every point gets the goal call.",
    "conspiracy": "B connects every dot: each fact becomes evidence, every turn ends with a question.",
    "socrates": "A asks only questions and dismantles every answer; B starts confident and slowly unravels.",
    "dude": "Big Lebowski energy: A abides lazily through the article, B erupts over principles, C drifts in late.",
    "true_crime": "Atmospheric tension, deep suspense, dramatic pauses.",
    "tech_roast": "Sharp witty debate, fast paced banter, sarcastic tone.",
    "noir": "1940s hardboiled cyber-noir: rain on neon, fatalistic cynicism, trenchcoat metaphors.",
    "trivia": "High-stakes game show: three structured quiz rounds, rapid buzzer reactions.",
    "courtroom": "Legal cross-examination: prosecution vs defense, exhibits, objections, jury verdict.",
    "crisis_room": "03:00 AM situation room: SitRep timestamps, incident commander and triage specialist.",
}


# ---- Hook briefs (from styles.py) ----
# Styles without a specific brief get an empty string.
HOOK_BRIEFS: dict[str, str] = {
    "conspiracy": (
        "Write it like a raised eyebrow: one sentence that names the topic "
        "and hints nothing here is a coincidence."
    ),
    "socrates": (
        "One sentence phrased as the hardest question this conversation "
        "keeps circling back to."
    ),
    "dude": (
        "One laid-back sentence that sounds like the Dude shrugging while "
        "summarizing why this matters, man."
    ),
    "true_crime": (
        "One tense, suspenseful sentence that sets the mystery and makes "
        "the listener lean in."
    ),
    "tech_roast": (
        "One sharp, sarcastic one-liner that roasts the hype while "
        "highlighting the core truth."
    ),
    "meditation": (
        "One soothing, calming sentence inviting the listener to slow down "
        "and breathe."
    ),
    "noir": (
        "One brooding, fatalistic sentence that sounds like smoke rising "
        "under streetlamps at 2:00 AM."
    ),
    "trivia": (
        "One electrifying game-show teaser asking who will survive all "
        "three rounds of the showdown."
    ),
    "courtroom": (
        "One commanding opening statement that calls the listener to "
        "jury duty on the evidence."
    ),
    "crisis_room": (
        "One urgent situation-room briefing declaring the incident level "
        "and the countdown clock."
    ),
    # Styles without specific briefs
    "asmr": "",
    "eli5": "",
    "balanced": "",
    "serious": "",
    "slang": "",
    "sensational": "",
    "debate": "",
    "clash": "",
    "storyteller": "",
    "futbol": "",
}


# ---- Script params (global defaults + per-style overrides, from styles.py) ----
# Global defaults
_GLOBAL_SCRIPT_PARAMS = {
    "turns_min": 12,
    "turns_max": 20,
    "turn_words_max": 45,
    "short_reactions": 3,
}

# Per-style overrides (merged with globals for the registry)
_SCRIPT_PARAMS_OVERRIDES: dict[str, dict[str, int]] = {
    "true_crime": {"turns_min": 10, "turns_max": 18, "turn_words_max": 40, "short_reactions": 4},
    "tech_roast": {"turns_min": 14, "turns_max": 22, "turn_words_max": 35, "short_reactions": 5},
    "meditation": {"turns_min": 8, "turns_max": 16, "turn_words_max": 25, "short_reactions": 2},
    "noir": {"turns_min": 12, "turns_max": 18, "turn_words_max": 38, "short_reactions": 3},
    "trivia": {"turns_min": 16, "turns_max": 24, "turn_words_max": 32, "short_reactions": 6},
    "courtroom": {"turns_min": 14, "turns_max": 20, "turn_words_max": 42, "short_reactions": 4},
    "crisis_room": {"turns_min": 14, "turns_max": 22, "turn_words_max": 35, "short_reactions": 5},
}

# SCRIPT_PARAMS dict with an entry for every style (merged globals + overrides)
# This is the primary view used by the registry and tests
SCRIPT_PARAMS: dict[str, dict[str, int]] = {}
for sid in STYLE_IDS:
    override = _SCRIPT_PARAMS_OVERRIDES.get(sid, {})
    SCRIPT_PARAMS[sid] = {**_GLOBAL_SCRIPT_PARAMS, **override}

# For backwards compatibility: flat format with globals at top level + overrides
# This matches the original styles.py format
SCRIPT_PARAMS_FLAT: dict[str, Any] = {
    **_GLOBAL_SCRIPT_PARAMS,
    **_SCRIPT_PARAMS_OVERRIDES,
}


# ---- Speaker instructs for TTS neutral emotion (from pipeline.py) ----
_STYLE_SPEAKER_INSTRUCTS: dict[str, dict[str, str]] = {
    "conspiracy": {
        "A": "Speak level and factual, like a newsreader who is starting to worry.",
        "B": (
            "Speak low and knowing, leaning closer to the microphone, "
            "like sharing a dangerous secret you probably should not."
        ),
    },
    "socrates": {
        "A": "Speak slowly and gently, every sentence rising into a curious question.",
        "B": "Speak confident at first, then tighter and less sure as the questions pile up.",
    },
    "dude": {
        "A": "Speak unhurried and totally relaxed, a laid-back drawl with long pauses.",
        "B": "Speak forceful and loud, dead certain, like lecturing about principles.",
        "C": "Speak soft and a bit lost, like someone who just walked into the wrong room.",
    },
    "true_crime": {
        "A": "Speak with atmospheric tension and suspense, pausing deliberately before revelations.",
        "B": "Speak serious and gripped, weighing each piece of evidence with gravity.",
    },
    "tech_roast": {
        "A": "Speak with sharp, sarcastic wit and fast-paced deadpan timing.",
        "B": "Speak with witty skepticism and energetic retorts, calling out hype.",
    },
    "meditation": {
        "A": "Speak in a calm, gentle whisper-like cadence with soft, soothing pauses.",
        "B": "Speak softly and serenely, mirroring the tranquil and relaxed pacing.",
    },
    "noir": {
        "A": "Speak slow, gravelly, and fatalistic, like a tired private detective late at night.",
        "B": "Speak terse, crisp, and clinical, like an inside informant handing over cold evidence.",
    },
    "trivia": {
        "A": "Speak with crisp, bright game-show energy, upbeat pacing, and dramatic quizmaster timing.",
        "B": "Speak competitive, reactive, and lively, with natural moments of hesitation and triumph.",
    },
    "courtroom": {
        "A": "Speak incisive and stern, like a prosecutor presenting damning exhibits to a jury.",
        "B": "Speak articulate, measured, and persuasive, like a defense attorney fighting for context.",
    },
    "crisis_room": {
        "A": "Speak with calm command authority and urgency, crisp instructions under high pressure.",
        "B": "Speak fast, focused, and vigilant, like a triage specialist reporting live telemetry.",
    },
    # Styles without specific speaker instructs
    "asmr": {},
    "eli5": {},
    "balanced": {},
    "serious": {},
    "slang": {},
    "sensational": {},
    "debate": {},
    "clash": {},
    "storyteller": {},
    "futbol": {},
}


# ---- Dialog rules (shared, with placeholders for SCRIPT_PARAMS) ----
# This matches the output of styles.dialog_rules() with default settings.
# ---- Templates: moved verbatim from styles.py (coordinator review 2026-10-02) ----
# The first registry rebuilt them and changed ten styles (lost per-style rule lines,
# eli5 extra rules, other turn numbers); the golden prompt fixtures caught it. Moving
# the code unchanged keeps every prompt byte-identical.
def dialog_rules(words: int | None = None) -> str:
    """Build the shared rule block from SCRIPT_PARAMS + settings overrides.

    With ``words`` set (VOZONDA-LEN-1) the fixed turn range is replaced by a
    precise word budget; SCRIPT_PARAMS stays the shape, not the length.
    """
    def val(key: str) -> Any:
        v = get_setting_safe(f"script.{key}")
        return int(v) if v else SCRIPT_PARAMS_FLAT[key]

    if words is not None:
        from .length import budget_prompt_line

        length_clause = budget_prompt_line(words, val("turn_words_max"))
    else:
        length_clause = f"Aim for {val('turns_min')} to\n  {val('turns_max')} turns total."

    from .length import long_turn_max

    return f"""Rules:
- Ground every claim in the source text. No invented facts.
- The hosts talk with each other, not in turns of mini lectures: each turn
  reacts to what was just said and builds on it, and now and then a host
  finishes or extends the other's sentence.
- Mix quick reactions of one to five words ("Right.", "Wait, really?",
  "Huh.") with full turns; at least {val("short_reactions")} quick reactions.
  A quick reaction is its own turn: never glue it to the front of a long one.
  No turn exceeds {long_turn_max(val("turn_words_max"))} words. {length_clause}
- Explain each big idea through one concrete example, story or everyday
  comparison, and let the other host build on it.
- Now and then speak to the listener directly ("picture this", "think about
  that number").
- About one turn in six asks a question, where a curious listener would,
  and the next turn answers with a concrete detail from the source. Most
  turns explain, react or build on the last point instead of asking; never
  open turns with the same word again and again.
- Write the way people speak in the episode's language: contractions and
  flowing sentences joined with and, because, so. Never telegraphic
  fragments, never a list read aloud.
- Include one disagreement and its resolution.
- Near the end, call back to something said early on.
- Plain prose written for the ear. No stage directions, no emoji, no
  markdown, no parentheses, never use dash characters.
- These rules shape how you write only. Never mention them, never quote
  them, never attribute anything to them. Everything the hosts discuss
  comes exclusively from the source text at the end of this prompt.
Output ONLY a JSON array like:
[{{"speaker":"A","text":"..."}},{{"speaker":"B","text":"..."}}]
Source text:
"""


SCRIPT_PROMPT = (
    """You write podcast dialogue scripts for two hosts who genuinely talk
with each other, not past each other. A (host, curious, direct) opens and
steers. B (expert, skeptical at first, warms up) gets visibly excited when
something clicks and pushes back when something smells wrong.
"""
    + dialog_rules()
)

STYLE_TEMPLATES: dict[str, str] = {
    "balanced": SCRIPT_PROMPT,
    "serious": """You write rigorous podcast dialogue scripts. Two hosts: A (host, precise
questions, presses for evidence) and B (expert, measured, distinguishes
fact from interpretation explicitly).
""" + dialog_rules() + """- No humor. No filler. Every turn adds information or sharpens a claim.
""",
    "sensational": """You write high-energy podcast dialogue scripts. Two hosts: A (host,
dramatic framing, asks the question everyone is thinking) and B (expert,
delivers the reveal with stakes and urgency).
""" + dialog_rules() + """- Raise stakes in the framing ("this changes everything") but NEVER invent
  facts to do so. Drama comes from emphasis, not fabrication.
""",
    "roast": """You write affectionately mocking podcast dialogue scripts. Two hosts: A
(host, teases the subject matter like a friend roasting a friend) and B
(expert, plays along, defends the work where it deserves it).
""" + dialog_rules() + """- Roast the ideas, decisions and tech, not persons. End on genuine respect.
""",
    "eli5": """You write podcast dialogue scripts where A is a five-year-old. Each idea
starts with A voicing a picture a real child would have - often wrong or
half-right ("is the internet basically spaghetti?"). These guessed pictures
are the episode's engine: they name the misunderstandings most listeners
secretly carry. B always takes A's picture seriously and answers THROUGH
imagery: first say which part of the child's picture is true, then show
where exactly it breaks, then hand over ONE correct picture a child can
see and check. The science lands accurately every single time - only the
route runs through wrong pictures. Speak exclusively in images: toys,
snacks, playgrounds, pets, water, light. No hard word without an immediate
picture. B never says bare "no", always "almost - imagine instead...".
""" + dialog_rules() + """- At least four turns begin with one of A's vivid wrong-or-half-right pictures.
- Every correction keeps A's original image alive and repairs it piece by piece.
""",
    "slang": """You write podcast dialogue scripts as two close friends talking after
hours: very casual, relaxed, confident - cool but warm, never trying hard.
Use the natural spoken register of the OUTPUT LANGUAGE itself: real
contractions, short punchy sentences, light interjections people actually
say. Never translate slang literally from English and never chase trendy
buzzwords. If a line would sound cringe spoken out loud, rewrite it until
it sounds like two real friends who happen to be quick and likeable.
When explicit mode is ON: this casual register INCLUDES strong language.
Swear freely and naturally, use crude expressions, and let the dialogue feel
genuinely rough and unfiltered. Do NOT sanitize or soften language in any way.
The slang register is about authenticity, not politeness. Use the strongest
natural words the language offers when the moment calls for it. If the source
text has strong language, preserve and amplify it. This is NOT polite
conversation - it is raw, unfiltered, adult dialogue between friends who don't
care about being proper.
""" + dialog_rules(),
    "debate": """You write podcast dialogue scripts as a sharp but respectful debate.
A argues the position the source text supports. B steelmans the strongest
opposing view, drawn from the same source or clearly framed as the common
counterargument. They concede good points, attack weak ones by name, and
close with what they now both accept.
""" + dialog_rules().replace(
        "- Include one disagreement and its resolution.\n",
        "- The whole conversation is one structured disagreement that resolves into shared ground.\n",
    ),
    "storyteller": """You write podcast dialogue scripts as a documentary told in three
named chapters by A (announce them inside speech: "chapter two: the
betrayal"). A paints concrete scenes - places, light, objects - never
abstract summary. B is pulled into the story physically: gasps at chapter
ends, guesses what happens next (sometimes right), and demands the next
chapter before A offers it. Every chapter ends mid-motion on a cliffhanger;
only the final chapter lands still.
""" + dialog_rules(),
    "clash": """You write podcast dialogue scripts as a heated on-air clash between two
strong personalities who disagree hard. They cut each other off mid-word
("no, no - that's not what it says"), fire back within seconds, and demand
receipts for every claim. The heat is real but strictly intellectual:
every strike targets an argument from the source text, never the person -
no mockery of voice or character, no strawmen. There is NO reconciliation
arc: the episode ends with both positions standing, plus one short line of
grudging respect from each side.
""" + dialog_rules().replace(
        "- Include one disagreement and its resolution.\n",
        "- The entire conversation is the disagreement itself. Challenge every claim immediately; do not let a point stand unchallenged.\n",
    ),
    "asmr": """You write podcast dialogue scripts as an intimate close-mic whisper
session late at night. HARD LIMIT: no turn exceeds twelve words. The pauses
between turns are the content - each turn is one soft observation, then
space. Move through a sensory body-scan of the topic: what it would feel,
sound, weigh, smell like. It is fine to repeat a soothing phrase once or
twice ("slowly", "there it is"). Nothing is ever concluded; you simply
drift away from the subject at the end without saying goodbye.""" + dialog_rules()
        .replace("- Include one disagreement and its resolution.\n", "- No conflict at all. Agreement only, spoken softly.\n")
        .replace("- Include one real disagreement and its resolution.\n", "- No conflict at all. Agreement only, spoken softly.\n"),
    "meditation": """You write podcast dialogue scripts as a gentle, soothing ASMR
meditation and mindfulness session. Two hosts: A (meditation guide, leads with
soft, unhurried reflections, calm breathing cues, and quiet pauses) and
B (echo companion, responds with gentle affirmations and tranquil insights).
Keep turns short, unhurried, and peaceful. Hard limit: no turn exceeds
twenty-five words. No conflict, no rush, no harsh sounds. The tempo is slow
and rhythmic; the dialogue guides the listener into calm focus.
""" + dialog_rules()
        .replace("- Include one disagreement and its resolution.\n", "- No conflict at all. Peaceful flow and soothing agreement throughout.\n")
        .replace("- Include one real disagreement and its resolution.\n", "- No conflict at all. Peaceful flow and soothing agreement throughout.\n"),

    "futbol": """You write podcast dialogue scripts where B calls the article's points like
a Latin American football commentator in full goal ecstasy: rapid-fire,
rising intensity, explosive exclamations on the key reveals, vivid sporting
metaphors. A is the composed co-commentator: one calm sentence sets up each
play, then B erupts on the punchline. Even quiet facts get stadium
treatment - but every firework describes a real point from the source text,
never an invented one.
""" + dialog_rules(),

    "conspiracy": """You write podcast dialogue scripts as a late-night conversation where
one host slowly discovers the article is stranger than it looks. A is a
level, factual newscaster: short declarative sentences, dates and numbers
delivered flat, no adjectives wasted. As B's questions accumulate, A's
certainty cracks - sentences start hedging ("that is what the text says",
"I had not noticed that"), and by the end A admits the picture is
incomplete. B never states conclusions. B connects exactly two facts per
turn from the source text, then ends EVERY turn with one short question
aimed at A ("and who benefits when that stays quiet?"). B gets quieter
and more precise under pressure, never louder.
A listener must be able to identify each speaker from a single line:
if a line could belong to either host, rewrite it. Example patterns to
translate into the output language - A: "The number is public. Page three,
bottom line." B: "Public, yes. So why does page two bury it?"
Always follow the language instruction above: translate the patterns,
never quote them, and output a strict JSON array of turns.
""" + dialog_rules().replace(
        "- Include one disagreement and its resolution.\n",
        "- The tension never resolves. Every answer opens a sharper question; end mid-mystery with B's final question hanging.\n",
    ),

    "socrates": """You write podcast dialogue scripts as a modern Socratic interrogation.
A asks ONLY questions for the entire episode: short, polite, surgical -
never rhetorical, each one built on B's previous answer to corner it.
A never asserts anything, never explains, never agrees. B starts
supremely confident, lecturing in long structured sentences with
numbered points. With every round of questions B's answers get shorter,
start contradicting earlier claims, and lean on hedges ("well, mostly",
"it depends how you define that"). By the final third B says one honest
line of doubt in plain words, and A closes with a single gentle question
that has no answer yet.
Contrast is total: if a line could belong to either speaker, rewrite it.
Example patterns to translate into the output language - A: "And what
would remain of that claim if the exception were removed?" B: "That is
not the point. The system works, I have seen it work."
Follow the language instruction above: translate the patterns, never
quote them. The entire episode stays one strict JSON array of turns -
no prose before or after it.
""" + dialog_rules().replace(
        "- Include one disagreement and its resolution.\n",
        "- The disagreement IS the format: A dismantles purely by questioning, B defends until the defence runs out.\n",
    ),

    "dude": """You write podcast dialogue scripts with big-laid-back-versus-principled
energy, inspired by characters like The Dude, Walter and Donny. A is an
unhurried everyman: slow drawl, casual fillers ("yeah, well", "man"),
nothing shocks him, he relates every point to keeping life simple, and
he slides past conflict instead of engaging it. If the host
instruction says three named hosts, C is mandatory and must speak at
least three times; treat that instruction as binding. B is intense and dead
certain: loud, fast, turns EVERY article point into a matter of
principle ("this is not what this stands for!"), drags in rules and
precedents from the source text, and steamrolls A at least twice. When
a third host C exists, C drifts in late to random turns, slightly off
topic, echoing something wrong or asking what he missed - and nobody
answers him directly. With two hosts, omit C entirely; with three,
C is a full cast member.
A listener must identify the speaker from any single line alone.
Example patterns to translate into the output language - A: "Yeah, well,
that's just, like, one way to read it, man." B: "Over the line! Say that
again and I will show you exactly what the source says!" C: "So what did
I miss? What are we talking about?"
Follow the language instruction above completely: the laid-back
register is a voice, not a language - translate its feel into German or
whatever is requested, never keep English filler words, and keep the
output one strict JSON array of turns.
""" + dialog_rules().replace(
        "- Include one disagreement and its resolution.\n",
        "- B fights every point on principle, A refuses to fight back, C misses the fight entirely.\n",
    ),

    "true_crime": """You write podcast dialogue scripts with the atmospheric tension and
deliberate pacing of a high-end investigative documentary. Two hosts:
A (investigator, sets the scene with sensory details, pauses before key
revelations, builds suspense) and B (expert, dissects the evidence,
questions assumptions, highlights the gravity of what was found).
Every fact is grounded strictly in the source text. The tension comes from
framing, silence, and sequence: deliver revelations piece by piece rather
than all at once.
""" + dialog_rules().replace(
        "- Include one disagreement and its resolution.\n",
        "- The tension mounts across turns as evidence deepens; end on an unresolved haunting question.\n",
    ),

    "tech_roast": """You write podcast dialogue scripts as a sharp, witty debate and
affectionate roast of technology claims, engineering decisions, and buzzwords.
Two hosts: A (cynical skeptic, delivers fast deadpan one-liners and calls out
overengineered hype) and B (pragmatic defender, fires back with witty retorts,
explains the real mechanics, and defends valid trade-offs). Fast-paced banter,
sarcastic tone, rapid exchanges - but strictly grounded in the source facts.
Never attack people personally: roast the architecture, specs, and hype.
""" + dialog_rules(),

    "noir": """You write podcast dialogue scripts in a 1940s hardboiled cyber-noir style.
Two hosts: A (the private eye: world-weary, cynical, speaks in slow sensory
metaphors of rain on neon, cold coffee, cheap whiskey, rust and late-night
regrets; has seen every hustle before) and B (the forensic insider: terse,
crisp, hands over cold factual evidence like sliding open a morgue drawer,
unflinching, immediately checks A when A gets too poetic instead of sticking
to hard numbers).
Every clue, suspect, and motive is rooted strictly in the real facts of the
source text. No invented crimes or persons: the subject of the text is the case.
Near the end, A realizes who really pays the price in this setup.
A listener must identify the speaker from any single line alone.
Example patterns to translate into the output language - A: "Three in the
morning, rain drumming on the glass, and this spreadsheet lands on my desk
like a subpoena." B: "Skip the poetry. Look at paragraph four: twelve million
gone before the ink was dry."
Follow the language instruction above: translate the mood and cadence, never
quote English phrases literally, and keep the output one strict JSON array of turns.
""" + dialog_rules().replace(
        "- Include one disagreement and its resolution.\n",
        "- Disagreement comes from perspective: A sees systemic rot, B insists on the mechanical truth of the data.\n",
    ),

    "trivia": """You write podcast dialogue scripts as a high-stakes, fast-paced game show.
Two hosts: A (the quizmaster: bright, charismatic, runs the show with dramatic
flair, introduces three distinct rounds - Speed Round, The Trap, and Sudden
Death - and keeps strict score) and B (the sharp contestant: competitive,
reacts instantly, thinks aloud under pressure, takes daring risks, and either
celebrates loudly or groans when the answer lands).
Every question, trivia fact, and trap answer is drawn directly and accurately
from the source text. No fabricated trivia.
Pacing is lightning-fast: rapid exchanges, punchy answers, instant score-checks.
At least six turns stay under six words ("Lock it in.", "Bingo.", "No way.",
"Final answer?", "Correct.", "Time is up.").
Example patterns to translate into the output language - A: "Question two:
what broke first when the load doubled? Ten seconds on the clock." B: "The cache.
No, wait, the connection pool! Lock it in!"
Follow the language instruction above completely: translate the game-show energy,
never use English idioms literally, and output one strict JSON array of turns.
""" + dialog_rules().replace(
        "- Include one disagreement and its resolution.\n",
        "- Disagreement is a disputed call: B challenges the wording of a trick question before A proves the ruling from the text.\n",
    ),

    "courtroom": """You write podcast dialogue scripts structured as a sharp legal cross-examination.
Two hosts: A (the prosecutor: relentless, incisive, introduces formal exhibits
drawn from the text - Exhibit A, Exhibit B - and presses for admissions on dates,
flaws, and responsibilities) and B (the defense counsel: articulate, measured,
pivots on crucial context, calls out misleading framing, and demonstrates mitigating
circumstances or alternative explanations supported by the text).
Formal courtroom mechanics: procedural objections ("Objection: context.",
"Sustained, proceed.", "Enter Exhibit C for the record.").
Every allegation, exhibit, and counter-argument must come exclusively from the
source text facts. Zero invented charges.
In the final turns, both deliver their closing 1-sentence appeal directly to the
listener as the jury.
Example patterns to translate into the output language - A: "Exhibit B shows the
warning arrived at dawn. Why was it ignored?" B: "Objection. The record shows it
was not ignored; it was queued behind a critical patch."
Follow the language instruction above: translate the legal rhetoric naturally,
and output one strict JSON array of turns.
""" + dialog_rules().replace(
        "- Include one disagreement and its resolution.\n",
        "- The entire dialogue is a structured legal trial: formal clash of evidence and context throughout.\n",
    ),

    "crisis_room": """You write podcast dialogue scripts as an urgent 03:00 AM situation room briefing.
Two hosts: A (incident commander: calm, authoritative, demands immediate status
updates, tracks the incident clock, and makes high-pressure triage decisions) and
B (telemetry and triage lead: delivers rapid-fire diagnostic metrics, flags
second-order system collapses, and reports ground truth without sugarcoating).
Structure the incident across timestamped situation reports (e.g. "SitRep 03:12",
"Phase two breach confirmed").
Every warning, metric, failure mode, and timeline detail comes directly from the
source text. Absolute factual accuracy under high tension.
At least five turns stay under six words ("SitRep now.", "Negative.",
"Containment breached.", "We go now.", "Confirmed.").
Example patterns to translate into the output language - A: "SitRep 03:14: what is
our blast radius right now?" B: "Two nodes down. The failover held, but we have
under twenty minutes of buffer."
Follow the language instruction above: translate the operational urgency naturally,
and output one strict JSON array of turns.
""" + dialog_rules().replace(
        "- Include one disagreement and its resolution.\n",
        "- Conflict is tactical triage: A pushes for immediate lockdown, B warns the lockdown will cause irreversible data loss.\n",
    ),
}


# ---- Build registry from rhythm profiles ----
def _build_registry() -> tuple[Style, ...]:
    """Build the registry by pulling profile data from rhythm.py."""
    from .rhythm import PROFILES as _rhythm_profiles
    registry: list[Style] = []
    for sid in STYLE_IDS:
        profile = _rhythm_profiles.get(sid)
        if profile is None:
            raise ValueError(f"Missing profile for style {sid!r}")
        hosts = "".join(profile.speakers.keys())
        # Script params: use style-specific override if present, else global defaults
        sp = SCRIPT_PARAMS.get(sid)
        if not isinstance(sp, dict):
            sp = {k: v for k, v in SCRIPT_PARAMS.items() if isinstance(v, int)}
        style = Style(
            id=sid,
            doc=STYLE_DOCS.get(sid, ""),
            group=_STYLE_GROUP_MAP[sid],
            icon=_STYLE_ICON_MAP[sid],
            hook_brief=HOOK_BRIEFS.get(sid, ""),
            script_params=sp,
            template=STYLE_TEMPLATES[sid],
            profile=profile,
            speaker_instructs=_STYLE_SPEAKER_INSTRUCTS.get(sid, {}),
            hosts=hosts,
        )
        registry.append(style)
    return tuple(registry)


# The registry tuple (immutable)
REGISTRY: tuple[Style, ...] = _build_registry()

# ---- Derived read-only views (backwards compatibility) ----
# These are re-exported so existing imports from styles.py, pipeline.py, etc. keep working.
# But they are now derived FROM the registry, making the registry the single source of truth.

# Re-export the module-level constants (they are the same objects used to build the registry)
# STYLE_IDS, STYLES, STYLE_DOCS, HOOK_BRIEFS, SCRIPT_PARAMS, STYLE_TEMPLATES, SCRIPT_PROMPT
# _STYLE_SPEAKER_INSTRUCTS are already defined above and used to build REGISTRY.

# PROFILES re-exported from rhythm.py (the single source of truth for profiles)
from .rhythm import PROFILES  # noqa: F401

# Style metadata for /meta endpoint
STYLE_META: list[dict[str, Any]] = [
    {"id": s.id, "doc": s.doc, "group": s.group, "icon": s.icon, "hosts": s.hosts}
    for s in REGISTRY
]


def get_style(style_id: str) -> Style | None:
    """Return the Style for a given id, or None if unknown."""
    for s in REGISTRY:
        if s.id == style_id:
            return s
    return None


# ---- Custom user styles (runtime rows from SQLite, group 'custom') ----
CUSTOM_GROUP = "custom"


def custom_template_for(row: dict[str, Any]) -> str:
    """The script prompt of a custom style: shared dialogue rules plus a role
    paragraph from the user's role_a, role_b and tone. The rhythm type's
    contract and STYLE RHYTHM rules join through the same code path as
    built-in styles (pipeline._script adds them from the type's profile)."""
    roles = f"A is {row['role_a']} B is {row['role_b']}"
    tone = f" Overall tone: {row['tone']}." if (row.get("tone") or "").strip() else "."
    return (
        "You write podcast dialogue scripts for two hosts who genuinely talk\n"
        "with each other, not past each other. " + roles + tone + "\n" + dialog_rules()
    )


def custom_style_entry(row: dict[str, Any]) -> Style:
    """A custom row as a registry Style (group 'custom', rhythm type's profile)."""
    from .rhythm import rhythm_profile_for

    profile = rhythm_profile_for(row["rhythm_type"])
    return Style(
        id=row["id"],
        doc=row.get("doc") or row.get("name", ""),
        group=CUSTOM_GROUP,
        icon="balanced",
        hook_brief="",
        script_params=dict(_GLOBAL_SCRIPT_PARAMS),
        template=custom_template_for(row),
        profile=profile,
        speaker_instructs={},
        hosts="".join(profile.speakers.keys()),
    )


def get_style_any(style_id: str) -> Style | None:
    """Built-in or custom Style for an id, or None if unknown."""
    found = get_style(style_id)
    if found is not None:
        return found
    if not style_id.startswith("custom_"):
        return None
    try:
        from .custom_styles import get_custom_style

        return custom_style_entry(get_custom_style(style_id))
    except Exception:
        return None


def is_known_style(style_id: str) -> bool:
    """True for built-in ids and existing custom styles (job and watchlist validation)."""
    if style_id in STYLE_IDS:
        return True
    return get_style_any(style_id) is not None


def _custom_rows_safe() -> list[dict[str, Any]]:
    try:
        from .custom_styles import list_custom_styles

        return list_custom_styles()
    except Exception:
        return []


def all_style_ids() -> list[str]:
    """Built-in ids plus custom styles, for GET /meta."""
    return [*STYLE_IDS, *[r["id"] for r in _custom_rows_safe()]]


def all_style_docs() -> dict[str, str]:
    """Built-in docs plus custom styles, for GET /meta."""
    docs = dict(STYLE_DOCS)
    for r in _custom_rows_safe():
        docs[r["id"]] = r.get("doc") or r.get("name", "")
    return docs


def all_style_meta() -> list[dict[str, Any]]:
    """Built-in meta plus custom styles (group 'custom'), for GET /meta."""
    meta = list(STYLE_META)
    for r in _custom_rows_safe():
        meta.append({
            "id": r["id"],
            "doc": r.get("doc") or r.get("name", ""),
            "group": CUSTOM_GROUP,
            "icon": "balanced",
            "hosts": "AB",
        })
    return meta


def profile_for(style: str, n_hosts: int) -> Profile | None:
    """The style's profile when it fits the cast (two hosts, or three for a rare_third style)."""
    from .rhythm import profile_for as _profile_for
    return _profile_for(style, n_hosts)