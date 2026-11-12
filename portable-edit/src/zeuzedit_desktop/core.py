"""NC operations. Comments are masked without changing character offsets."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

WORD = re.compile(r"([A-Za-z])([ \t]*)([+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+))")
LEADING_N = re.compile(r"^[ \t]*N\d+[ \t]*", re.I)


def code_mask(text: str) -> str:
    depth = 0
    semicolon = False
    result = []
    for char in text:
        if char in "\r\n":
            semicolon = False
            result.append(char)
        elif semicolon:
            result.append(" ")
        elif char == "(":
            depth += 1
            result.append(" ")
        elif depth:
            if char == ")":
                depth -= 1
            result.append(" ")
        elif char == ";":
            semicolon = True
            result.append(" ")
        else:
            result.append(char)
    return "".join(result)


def words(text: str):
    yield from WORD.finditer(code_mask(text))


def _lines(text: str):
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        yield body, line[len(body):]


def renumber(text: str, start: int = 10, step: int = 10, missing_only: bool = False) -> str:
    number = start
    out = []
    for (line, ending), (masked, _) in zip(_lines(text), _lines(code_mask(text))):
        trim = line.strip()
        first = len(line) - len(line.lstrip(" \t"))
        comment_prefix = first < len(line) and masked[first] == " "
        if not masked.strip() or comment_prefix or trim.startswith(("%", "(", ";", "O", "o")) or (missing_only and LEADING_N.match(line)):
            out.append(line + ending)
            continue
        out.append(f"N{number} {LEADING_N.sub('', line).strip()}" + ending)
        number += step
    return "".join(out)


def remove_numbers(text: str) -> str:
    return "".join((LEADING_N.sub("", line) if LEADING_N.match(masked) else line) + ending
                   for (line, ending), (masked, _) in zip(_lines(text), _lines(code_mask(text))))


def format_spacing(text: str) -> str:
    out = []
    previous_space = False
    depth = 0
    semicolon = False
    for char in text:
        in_comment = bool(depth or semicolon)
        if char in "\r\n":
            semicolon = False
        elif not semicolon and char == "(":
            depth += 1
        elif depth and char == ")":
            depth -= 1
        elif not depth and char == ";":
            semicolon = True
        if char in " \t" and not in_comment:
            if not previous_space:
                out.append(" ")
            previous_space = True
        else:
            out.append(char)
            previous_space = False
    return "".join(out)


def uppercase_code(text: str) -> str:
    return "".join(char.upper() if mask != " " else char for char, mask in zip(text, code_mask(text)))


def scale_words(text: str, letter: str, factor: float) -> str:
    if not math.isfinite(factor) or factor < 0:
        raise ValueError("El factor debe ser positivo y finito")
    replacements = []
    for match in words(text):
        if match[1].upper() != letter.upper():
            continue
        original = match[3]
        value = float(original) * factor
        if not math.isfinite(value):
            raise ValueError("El resultado excede el límite numérico")
        decimals = min(4, max(1, len(original.split(".", 1)[1]))) if "." in original else 0
        if decimals == 0:
            formatted = str(math.floor(value + .5) if value >= 0 else math.ceil(value - .5))
        else:
            formatted = f"{value:.{decimals}f}"
        replacements.append((match.start(3), match.end(3), formatted))
    for start, end, value in reversed(replacements):
        text = text[:start] + value + text[end:]
    return text


def remove_mcodes(text: str, codes: set[int]) -> str:
    replacements = [(m.start(), m.end()) for m in words(text)
                    if m[1].upper() == "M" and "." not in m[3] and int(m[3]) in codes]
    cleaned = text
    for start, end in reversed(replacements):
        cleaned = cleaned[:start] + cleaned[end:]
    out = []
    for (original, original_end), (line, ending) in zip(_lines(text), _lines(cleaned)):
        if original != line and not LEADING_N.sub("", line).strip():
            continue
        out.append((line.strip() if original != line else line) + ending)
    return "".join(out)


@dataclass(frozen=True)
class Analysis:
    lines: int
    tools: tuple[str, ...]
    units: str
    axes: dict[str, tuple[float, float]]
    warnings: tuple[str, ...]


def analyze(text: str) -> Analysis:
    tools = []
    axes: dict[str, tuple[float, float]] = {}
    units = "No declaradas"
    ended = False
    for match in words(text):
        letter, number = match[1].upper(), match[3]
        value = float(number)
        if letter == "T" and number not in tools:
            tools.append(number)
        if letter == "G" and value in {20, 21}:
            units = "Pulgadas (G20)" if value == 20 else "Milímetros (G21)"
        if letter in "XYZ":
            previous = axes.get(letter, (value, value))
            axes[letter] = (min(value, previous[0]), max(value, previous[1]))
        ended |= letter == "M" and value in {2, 30}
    warnings = []
    if not ended and text.strip():
        warnings.append("No se encontró M2/M30 de fin de programa.")
    if text.count("(") != text.count(")"):
        warnings.append("Revisa los paréntesis de comentarios.")
    if re.search(r"\bG\s*91(?:\D|$)", code_mask(text), re.I):
        warnings.append("Hay G91: los rangos muestran valores escritos, no posiciones acumuladas.")
    return Analysis(len(text.splitlines()), tuple(tools), units, axes, tuple(warnings))
