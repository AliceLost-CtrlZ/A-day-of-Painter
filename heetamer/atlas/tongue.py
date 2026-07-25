"""Three invented languages, and the names they give the country.

Each tongue has a hearth somewhere on the map, a phoneme inventory, a small
lexicon of proto-morphemes, and an ordered list of sound laws. Names are built
by compounding morphemes that are *true of the site* -- a town at a river mouth
is literally called mouth-of-the-water -- and then aged.

The ageing is the point. Innovations radiate outward from the hearth, so a
place is eroded in proportion to how easily a traveller reaches it. Distance is
measured in walking effort over the real terrain, which means a mountain range
holds back sound change and leaves archaic forms in the valleys behind it. The
isoglosses on the map are consequences of the topography, not decoration.
"""

import re

import numpy as np

CONCEPTS = [
    "water", "river", "mouth", "ford", "bridge", "lake", "sea", "bay", "haven",
    "island", "cape", "hill", "mountain", "high", "pass", "stone", "cliff",
    "forest", "oak", "pine", "birch", "reed", "marsh", "meadow", "grass",
    "moor", "cold", "warm", "dry", "black", "white", "red", "grey", "green",
    "old", "new", "far", "quiet", "town", "fort", "gate", "market", "house",
    "hall", "king", "folk", "road", "wall", "field", "mill", "salt", "iron",
    "ash", "spring", "narrow", "broad", "deep", "shelter", "bend", "land",
]

GLOSS = {c: c for c in CONCEPTS}
GLOSS.update({"haven": "harbour", "folk": "people", "moor": "heath"})


# --- sound laws -----------------------------------------------------------
# Each law is (name, human-readable description, regex, replacement).
# They are applied in order; a name undergoes the first `k` of them.

V = "aeiou"
LAW_POOL = [
    ("lenition", "voiceless stops soften between vowels",
     rf"([{V}])p([{V}])", r"\1v\2"),
    ("lenition-t", "t weakens between vowels",
     rf"([{V}])t([{V}])", r"\1d\2"),
    ("lenition-k", "k weakens between vowels",
     rf"([{V}])k([{V}])", r"\1g\2"),
    ("spirantise", "g becomes a breath between vowels",
     rf"([{V}])g([{V}])", r"\1h\2"),
    ("palatal", "k fronts before i and e",
     r"k([ie])", r"c\1"),
    ("palatal-s", "s hushes before front vowels",
     r"s([ie])", r"x\1"),
    ("apocope", "final short vowels fall away",
     rf"([bcdfghklmnprstvxzj])[{V}]$", r"\1"),
    ("syncope", "a vowel drops between two liquids",
     rf"([lr])[{V}]([lrn])", r"\1\2"),
    ("raise-a", "long a raises toward e",
     r"aa", "ee"),
    ("raise-e", "e raises toward i in closed syllables",
     rf"e([bcdfgklmnprstvxz][bcdfgklmnprstvxz])", r"i\1"),
    ("rhotic", "s becomes r between vowels",
     rf"([{V}])s([{V}])", r"\1r\2"),
    ("h-loss", "initial h is lost",
     r"^h", ""),
    ("degemination", "doubled consonants simplify",
     r"([bcdfgklmnprstvxz])\1", r"\1"),
    ("w-shift", "w hardens to v",
     r"w", "v"),
    ("nasal-loss", "a nasal before a stop leaves the vowel long",
     r"n([bcdfgkpt])", r"\1"),
    ("cluster", "an awkward onset takes a prop vowel",
     r"^([bcdfgkpt])([lrmn])", r"\1e\2"),
    ("final-devoice", "final voiced stops harden",
     r"b$", "p"),
    ("umlaut", "a following i colours the vowel before it",
     rf"a([bcdfgklmnprstvxz]+)i", r"e\1i"),
    ("diphthong", "o before a liquid breaks",
     r"o([lr])", r"ou\1"),
    ("t-loss", "t falls between a liquid and a vowel",
     rf"([lr])t([{V}])", r"\1\2"),
]


def _romanise(s, style):
    """Turn the phonemic string into that culture's spelling."""
    out = s
    for a, b in style:
        out = out.replace(a, b)
    return out


ORTHO_STYLES = {
    # x = the hushing sound; c = the fronted k; h after a vowel = breath
    "coastal": [("x", "sh"), ("c", "ch"), ("j", "y"), ("kw", "qu")],
    "highland": [("x", "sc"), ("c", "k"), ("j", "i"), ("v", "w")],
    "riverine": [("x", "ss"), ("c", "tz"), ("j", "j"), ("h", "gh")],
}


class Tongue:
    def __init__(self, name, hearth, rng, style, onset, coda, vowels,
                 head_final=True, linker="", genitive="", law_seed=None):
        self.name = name
        self.hearth = hearth          # (y, x) on the full-resolution grid
        self.style = style
        self.onset = onset
        self.coda = coda
        self.vowels = vowels
        self.head_final = head_final
        self.linker = linker
        self.genitive = genitive
        self.rng = rng
        # Each tongue runs its own subset of the laws, in its own order.
        pool = list(LAW_POOL)
        rng.shuffle(pool)
        self.laws = pool[: rng.integers(11, 15)]
        self.lex = {c: self._coin(rng) for c in CONCEPTS}
        self._dedupe()

    # -- lexicon ------------------------------------------------------
    def _syll(self, rng, heavy=False):
        s = rng.choice(self.onset) + rng.choice(self.vowels)
        if heavy or rng.random() < 0.40:
            s += rng.choice(self.coda)
        return s

    def _coin(self, rng):
        # Roots are overwhelmingly monosyllabic: compounds get long enough
        # on their own, and the sound laws need something to chew on.
        for _ in range(40):
            n = 1 if rng.random() < 0.80 else 2
            w = "".join(self._syll(rng, heavy=(i == 0 and n == 1)) for i in range(n))
            if len(w) <= (4 if n == 1 else 6):
                return w
        return w

    def _dedupe(self):
        seen = {}
        for c in CONCEPTS:
            w = self.lex[c]
            while w in seen:                    # mutate rather than lengthen
                i = int(self.rng.integers(0, len(w)))
                w = w[:i] + str(self.rng.choice(self.vowels
                                                if w[i] in V else self.onset)) + w[i + 1:]
                w = self._repair(w)
            seen[w] = c
            self.lex[c] = w

    # -- ageing -------------------------------------------------------
    def n_laws_at(self, frac):
        """How many innovations have reached a place `frac` of the way out.

        frac == 0 at the hearth, 1 at the far edge of the tongue's range.
        The core innovates; the periphery keeps the old shapes -- but even the
        remotest valley has undergone the earliest changes, so the floor is
        well above zero.
        """
        f = float(np.clip(frac, 0.0, 1.0))
        share = 1.0 - 0.62 * f ** 0.85       # 1.00 at the hearth, 0.38 at the rim
        return int(round(len(self.laws) * share))

    def age(self, word, k, trace=False):
        applied = []
        for law in self.laws[:k]:
            nm, desc, pat, rep = law
            new = re.sub(pat, rep, word)
            if new != word:
                applied.append((nm, desc, word, new))
                word = new
        return (word, applied) if trace else word

    # -- naming -------------------------------------------------------
    C = "bcdfghjklmnprstvwxz"

    def _repair(self, s):
        """Tidy the seam, and enforce the tongue's own phonotactics."""
        s = re.sub(rf"([{self.C}]{{3,}})", lambda m: m.group(1)[0] + m.group(1)[-1], s)
        s = re.sub(rf"([{self.C}])\1", r"\1", s)
        s = re.sub(rf"([{V}]{{3,}})", lambda m: m.group(1)[:2], s)
        # A word may only begin with a cluster the tongue actually permits.
        # Anything else takes a prop vowel, as such words really do.
        m = re.match(rf"^([{self.C}])([{self.C}])", s)
        if m and (m.group(1) + m.group(2)) not in self.onset:
            s = m.group(1) + (self.linker or "e") + s[1:]
        return s

    def demo_root(self, options):
        """Pick the compound that best shows this tongue's changes at work."""
        best, score = options[0], -1
        for parts in options:
            forms = [self.name_for(parts, f) for f in (0.0, 0.34, 0.67, 1.0)]
            n = len(set(forms))
            if n > score:
                score, best = n, parts
            if n == 4:
                break
        return best

    def compound(self, parts):
        """parts: list of concepts, modifier(s) first in my notation."""
        forms = [self.lex[p] for p in parts]
        if not self.head_final:
            forms = forms[::-1]
        out = forms[0]
        for f in forms[1:]:
            if out[-1] not in V and f[0] not in V:
                out += self.linker
            out += f
        return self._repair(out)

    def spell(self, phonemic):
        return _romanise(phonemic, ORTHO_STYLES[self.style]).capitalize()

    def name_for(self, parts, frac, trace=False):
        proto = self.compound(parts)
        k = self.n_laws_at(frac)
        if trace:
            aged, applied = self.age(proto, k, trace=True)
            aged = self._repair(aged)
            return _romanise(aged, ORTHO_STYLES[self.style]).capitalize(), proto, applied
        aged = self._repair(self.age(proto, k))
        return _romanise(aged, ORTHO_STYLES[self.style]).capitalize()

    def gloss(self, parts):
        """English rendering of the compound, modifier-first as English does."""
        return "-".join(GLOSS[p] for p in parts)


def make_tongues(rng, hearths):
    """Three related-but-distinct tongues, one per hearth."""
    specs = [
        dict(name="Ammoric", style="coastal", head_final=False, linker="a",
             onset=list("ptkmnlrsvh") + ["th", "kw", "br", "gl"],
             coda=list("nlrsmt"), vowels=list("aeiou") + ["aa", "ei"],
             genitive="-an"),
        dict(name="Vennuk", style="highland", head_final=True, linker="e",
             onset=list("tkgdbnmrsx") + ["kr", "st", "sk", "gn"],
             coda=list("kngrtsx"), vowels=list("aeiou") + ["uu", "au"],
             genitive="-uk"),
        dict(name="Selane", style="riverine", head_final=True, linker="i",
             onset=list("slmnfvzdhj") + ["sl", "fl", "mr", "dz"],
             coda=list("lnszrf"), vowels=list("aeiou") + ["ie", "oo"],
             genitive="-is"),
    ]
    out = []
    for spec, hearth in zip(specs, hearths):
        sub = np.random.default_rng(rng.integers(1 << 30))
        out.append(Tongue(hearth=hearth, rng=sub, **spec))
    return out
