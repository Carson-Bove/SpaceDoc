"""Keeping the model's questions in step with its message and with what was already asked.

A small model often lists a question it never wrote in its message, gives two questions the
same topic, or asks again what the user already answered. These checks run in code, after
every reply, so the cards under a message always match it and a repeat never reaches the
user.
"""

from __future__ import annotations

import re

from spacedoc.consult.schema import Question, TurnReply

# Words that carry no meaning for comparing two questions.
_STOP = set(
    """a an and any anything are be been being can could did do does doing for from had has
    have having how i if in is it its me my of on or our patient please recent recently say
    tell that the their them there they this to was we were what when where whether which
    who will with you your she he her his him""".split()
)
_SENTENCE = re.compile(r"(?<=[.?!])\s+")
REPEAT_OVERLAP = 0.6


def _stem(word: str) -> str:
    for suffix in ("ing", "edly", "ed", "ly", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def content_words(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {_stem(w) for w in words if w not in _STOP and len(w) > 2}


def similar(a: str, b: str) -> bool:
    """Whether two questions ask the same thing: most content words of the shorter one appear
    in the other ("Has the patient hit their head?" and "Have you hit your head?")."""
    wa, wb = content_words(a), content_words(b)
    if not wa or not wb:
        return False
    shorter = min(len(wa), len(wb))
    return shorter >= 2 and len(wa & wb) / shorter >= REPEAT_OVERLAP or wa == wb


def question_sentences(message: str) -> list[str]:
    """The sentences of a message that ask something."""
    return [s for s in _SENTENCE.split(message.replace("\n", " ")) if "?" in s]


def _drop_sentence(message: str, question: str) -> str:
    """Remove the sentence of `message` that asks `question`, keeping paragraphs."""
    paragraphs = []
    for para in message.split("\n\n"):
        kept = [s for s in _SENTENCE.split(para.strip()) if not ("?" in s and similar(s, question))]
        if kept:
            paragraphs.append(" ".join(kept))
    return "\n\n".join(paragraphs)


def clean(reply: TurnReply, answered: list[str]) -> list[str]:
    """Fix the reply's questions in place; return the questions dropped as repeats.

    - A question with no `ask` gets its topic, so its card always shows a question.
    - A second question asking the same as the first is dropped.
    - A question the user has already answered is dropped, and so is its sentence in the
      message.
    - A question the model listed but did not write in its message is added to the message,
      so the cards never ask something the message does not.
    """
    kept: list[Question] = []
    dropped: list[str] = []
    for q in reply.questions:
        q.ask = q.ask.strip()
        from_topic = not q.ask
        if from_topic:
            q.ask = q.topic.strip()[:1].upper() + q.topic.strip()[1:]
        if any(similar(q.ask, k.ask) or q.topic.lower() == k.topic.lower() for k in kept):
            continue
        if any(similar(q.ask, a) for a in answered):
            dropped.append(q.ask)
            reply.message = _drop_sentence(reply.message, q.ask)
            continue
        if not from_topic and not any(similar(q.ask, s) for s in question_sentences(reply.message)):
            reply.message = f"{reply.message}\n\n{q.ask}".strip()
        kept.append(q)
    reply.questions = kept
    return dropped
