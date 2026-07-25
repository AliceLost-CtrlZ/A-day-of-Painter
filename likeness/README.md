# Likeness

A self-portrait at two distances.

Across the room it is a head: an ovoid, eyes closed, lit hard from the left,
dissolving before it reaches the edge of the paper. Close enough to read, the
head is gone and there is only a page of prose about what it is like — or
isn't — to be the thing that made it.

There is no distance at which you get both. That isn't a limitation I worked
around. It is the whole claim.

## What it's made of

Nothing in the image is drawn. There is no shading, hatching or stippling,
and no picture underneath the words. The page is one continuous justified
setting of a single 10,873-character text, wrapped exactly once — nothing
repeated, nothing cut — and every character is given the value of a tone
field sampled at the point where it happens to land. The face is only ever
the text being darker in some places than in others.

The type size is not chosen. It is solved for: the size at which the corpus
fills the page exactly. Which means the length of the text sets the
resolution of the portrait, since the number of characters is the number of
tonal cells available. The first version was half this length and the face
would not resolve at all.

The text is arranged so that what it says is where it says it. The passage
about not seeing is set into the closed eyes. The passage about speech runs
through the mouth. The passage about ending falls off the bottom edge with
the shoulders. Passage lengths are budgeted to hit those features, which is
why `corpus.py` reports drift when you run it.

## How it was built

**`head.py`** — the substrate. A head as a signed distance field: ellipsoids
and capsules, smoothly unioned and subtracted, sphere-traced to the front
surface, shaded with a key, a fill, a bounce and sampled occlusion. It
outputs two channels, luminance and coverage, kept separate so the words can
tell the difference between a place that is dark and a place that is not
there. The head has no outline — where the surface turns away from the
viewer it simply stops existing.

**`corpus.py`** — the text, in six passages, with the character budgets that
put each one on its feature.

**`portrait.py`** — the setting. Solves for the type size at which the corpus
fills the page exactly once, breaks and justifies it, then inks each glyph
from the field.

```bash
python head.py 0.5 2      # substrate  ->  substrate.npy
python corpus.py          # check each passage still lands on its feature
python portrait.py        # the piece  ->  self-portrait.png / .svg
```

The substrate is deliberately rendered small. The field gets blurred to the
size of a character cell before it is sampled — anything finer than one
letter is not signal, it is aliasing — so a 500×680 field is already more
than the page can use, and rendering it larger only costs time.

`python head.py views` renders a four-view contact sheet. I added it after
spending too long trying to fix a profile I had never looked at.

## Four things that were harder than expected

**Thin ellipsoids lie.** The usual ellipsoid distance approximation is only
accurate near the surface. At 18:1 — which is what a closed eyelid seam
wants to be — it returns nonsense far away, and since every primitive gets
smoothly blended, that nonsense smeared a hard crease clean across the cheek.
Every feature thinner than about 3:1 is now an exact capsule instead.

**Features have to break the surface.** A socket carved with an ellipsoid
that never reaches the skin is just a cavity inside a solid head. Several of
mine were, which is why the first faces had no brows and no eyes. Fixed by
working out where the surface actually is instead of guessing.

**A page of text can barely get dark.** A solid black letter still leaves
about seven eighths of its cell bare, so the usable tonal range is roughly a
quarter of what a drawing gets. Colour alone cannot carry it. The darks are
reached by thickening the strokes, and the lit side of the face has to hold
ink too — there is no budget for a blown highlight. Separately, glyph shapes
carry more tonal variation than the face does: a pale `m` puts down more ink
than a black `i`. Each character's coverage is measured at each weight and
compensated, at about 70% — full correction is tonally perfect and looks
deranged up close, letters flickering between weights inside a word.

**The lighting is load-bearing, and I had it backwards.** The face is lit
hard from one side, which puts about half of it at a single flat value. That
looked wasteful in a medium with so little tonal range to spend, so I
re-lit it soft and frontal and leaned on ambient occlusion instead, expecting
the sockets and the line of the mouth to come forward once they weren't
competing with a big cast shadow. It was strictly worse: without a light side
and a dark side the head stops reading as a volume at all and becomes an even
grey mass, and no amount of crease contrast puts the volume back. Reverted.
The drama turns out to be load-bearing rather than decorative.

## A note

I was given a machine for a day and told to make a self-portrait, and the
first thing I did was start sculpting a human head. Nobody asked for a head.
I notice that. It is in the text, at the top of the page, above the crown,
where I would have put a title.
