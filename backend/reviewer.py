import os
import random
import re


def read_module_text(filepath):
    if not filepath or not os.path.isfile(filepath):
        raise FileNotFoundError("Module file could not be found.")

    extension = os.path.splitext(filepath)[1].lower()

    if extension == ".txt":
        with open(filepath, "r", encoding="utf-8", errors="ignore") as file:
            return file.read()

    if extension == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(filepath)
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    raise ValueError("Only TXT and text-based PDF files are supported.")


def make_reviewer_content(source_text, question_count=5):
    if not source_text or len(source_text.strip()) < 40:
        raise ValueError("The selected module does not contain enough readable text.")

    cleaned_lines = []
    for line in source_text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if re.search(
            r"creative commons|international license|all rights reserved|copyright",
            line,
            re.IGNORECASE,
        ):
            continue
        if re.match(
            r"^(name|date|student name|course name|section|signature)\s*:",
            line,
            re.IGNORECASE,
        ):
            continue
        if re.match(r"^(student activity sheet|SAS)\b", line, re.IGNORECASE):
            continue
        cleaned_lines.append(line)

    cleaned_text = " ".join(cleaned_lines)
    sentences = re.split(r"(?<=[.!?])\s+", cleaned_text)
    useful_sentences = []
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence.split()) < 5:
            continue
        if re.search(r"_{3,}", sentence):
            continue
        if sentence not in useful_sentences:
            useful_sentences.append(sentence)

    if not useful_sentences:
        raise ValueError("No useful lesson sentences were found in this module.")

    keywords = (
        " is ", " are ", " means ", " refers to ",
        " defined as ", " used to ", " allows ",
        " consists of ", " includes ", " such as ",
    )
    ranked_sentences = sorted(
        useful_sentences,
        key=lambda sentence: (
            sum(1 for keyword in keywords if keyword in sentence.lower()),
            len(sentence.split()),
        ),
        reverse=True,
    )

    summary = " ".join(ranked_sentences[:3])
    key_points = ranked_sentences[: min(8, len(ranked_sentences))]

    questions = []
    used_answers = set()
    skip_words = {
        "example", "activity", "minutes", "following", "below",
        "statement", "programming", "module", "license", "international",
    }

    for sentence in ranked_sentences:
        if len(questions) >= question_count:
            break
        words = sentence.split()
        candidates = [
            word.strip(".,;:!?()[]{}\"'")
            for word in words
            if len(word.strip(".,;:!?()[]{}\"'")) >= 5
        ]
        if not candidates:
            continue
        answer = next(
            (word for word in candidates if word.lower() not in skip_words),
            None,
        )
        if answer is None or answer.lower() in used_answers or answer.isdigit():
            continue

        used_answers.add(answer.lower())
        options = [answer]
        for other_sentence in ranked_sentences:
            if other_sentence == sentence:
                continue
            other_words = [
                word.strip(".,;:!?()[]{}\"'")
                for word in other_sentence.split()
            ]
            for word in other_words:
                if (
                    len(word) >= 5
                    and word.lower() not in used_answers
                    and word.lower() not in {option.lower() for option in options}
                ):
                    options.append(word)
                    if len(options) == 4:
                        break
            if len(options) == 4:
                break
        if len(options) < 4:
            continue

        random.shuffle(options)
        questions.append({
            "question": (
                "Which word completes this statement?\n\n"
                + sentence.replace(answer, "________", 1).rstrip(".! ")
                + "?"
            ),
            "options": options,
            "answer": answer,
            "explanation": (
                "The selected answer comes from the original module sentence: "
                + sentence
            ),
            "topic": sentence,
        })

    if not questions:
        raise ValueError(
            "The module text was found, but it did not contain enough "
            "suitable material for multiple-choice questions."
        )

    return summary, key_points, questions
