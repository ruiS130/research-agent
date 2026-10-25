"""Fixed research questions for before/after quality checks.

Facts and aspects are phrases a correct report should contain. Matching is
lexical, so a paraphrase can score low even when it is right. Use a drop
against a saved baseline as a reason to revert. Do not treat the absolute
score as a grade.
"""

from __future__ import annotations

from dataclasses import dataclass

# Any one string in the tuple satisfies the fact or aspect.
Phrase = tuple[str, ...]


@dataclass(frozen=True)
class EvalCase:
    id: str
    topic: str
    facts: tuple[Phrase, ...]
    aspects: tuple[Phrase, ...]
    min_sources: int = 1


EVAL_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        id="water-boiling-point",
        topic="What is the boiling point of water at standard atmospheric pressure?",
        facts=(
            (
                "100°c",
                "100 °c",
                "100 degrees celsius",
                "100 celsius",
                "212°f",
                "212 °f",
                "212 degrees fahrenheit",
            ),
        ),
        aspects=(
            ("celsius", "fahrenheit"),
            ("atmospheric pressure", "sea level", "1 atm", "one atmosphere"),
        ),
        min_sources=1,
    ),
    EvalCase(
        id="japan-capital",
        topic="What is the capital city of Japan?",
        facts=(("tokyo",),),
        aspects=(("capital",), ("japan",)),
        min_sources=1,
    ),
    EvalCase(
        id="origin-of-species",
        topic="Who wrote On the Origin of Species, and what idea does the book argue for?",
        facts=(("charles darwin", "darwin"),),
        aspects=(("natural selection",), ("evolution",)),
        min_sources=1,
    ),
    EvalCase(
        id="speed-of-light",
        topic="What is the speed of light in a vacuum?",
        facts=(
            (
                "299,792",
                "299792",
                "2.998",
                "3 × 10",
                "3 x 10",
                "300,000 km",
                "300,000 kilometers",
            ),
        ),
        aspects=(
            ("vacuum",),
            ("meters per second", "m/s", "kilometres per second", "kilometers per second"),
        ),
        min_sources=1,
    ),
    EvalCase(
        id="gold-symbol",
        topic="What is the chemical symbol for gold?",
        facts=(("au",),),
        aspects=(("transition metal", "group 11", "noble metal"), ("periodic table",)),
        min_sources=1,
    ),
    EvalCase(
        id="iphone-announcement",
        topic="When did Apple announce the first iPhone, and who presented it?",
        facts=(("2007",), ("steve jobs",)),
        aspects=(("january", "macworld"), ("iphone",)),
        min_sources=1,
    ),
    EvalCase(
        id="photosynthesis",
        topic="How does photosynthesis turn light into chemical energy in plants?",
        facts=(("chlorophyll",), ("carbon dioxide", "co2")),
        aspects=(
            ("sunlight", "light energy"),
            ("glucose", "sugar", "carbohydrate"),
            ("oxygen",),
        ),
        min_sources=2,
    ),
    EvalCase(
        id="crispr-cas9",
        topic="What is CRISPR-Cas9 and what is it used for?",
        facts=(("gene editing", "genome editing"), ("cas9",)),
        aspects=(("guide rna", "grna"), ("dna",), ("doudna", "charpentier")),
        min_sources=2,
    ),
    EvalCase(
        id="paris-agreement",
        topic="What is the Paris Agreement and what temperature goal does it set?",
        facts=(("2015",), ("1.5", "2°c", "2 °c", "2 degrees")),
        aspects=(
            ("climate",),
            ("greenhouse", "emissions"),
            ("united nations", "unfccc", "cop21"),
        ),
        min_sources=2,
    ),
    EvalCase(
        id="moores-law",
        topic="What does Moore's law claim about integrated circuits?",
        facts=(("gordon moore", "moore"), ("transistor",)),
        aspects=(
            ("double", "doubling", "doubled"),
            ("integrated circuit", "microchip"),
            ("two years", "18 months", "every two years"),
        ),
        min_sources=2,
    ),
    EvalCase(
        id="ocean-tides",
        topic="What causes ocean tides?",
        facts=(("moon",), ("gravity", "gravitational")),
        aspects=(("sun",), ("high tide", "low tide", "tidal")),
        min_sources=2,
    ),
    EvalCase(
        id="lithium-ion",
        topic="How does a lithium-ion battery store and release energy?",
        facts=(("anode",), ("cathode",), ("electrolyte",)),
        aspects=(
            ("lithium ion", "lithium ions"),
            ("intercalation", "intercalate"),
        ),
        min_sources=2,
    ),
    EvalCase(
        id="tcp-vs-udp",
        topic="How do TCP and UDP differ?",
        facts=(("connection",), ("datagram", "connectionless")),
        aspects=(
            ("reliable", "retransmission", "guaranteed delivery"),
            ("packet",),
        ),
        min_sources=2,
    ),
    EvalCase(
        id="black-holes",
        topic="What is a black hole?",
        facts=(("event horizon",),),
        aspects=(
            ("gravity", "gravitational"),
            ("light",),
            ("singularity", "spacetime", "space-time"),
        ),
        min_sources=2,
    ),
    EvalCase(
        id="mrna-vaccines",
        topic="How do mRNA vaccines produce an immune response?",
        facts=(("spike protein", "spike"), ("lipid nanoparticle", "lnp")),
        aspects=(
            ("ribosome", "translation"),
            ("immune", "antibody"),
            ("covid", "sars-cov-2"),
        ),
        min_sources=2,
    ),
    EvalCase(
        id="solid-state-batteries",
        topic="What are the advantages and open problems of solid-state batteries?",
        facts=(("solid electrolyte",),),
        aspects=(("energy density",), ("dendrite",), ("lithium",)),
        min_sources=2,
    ),
)
