#!/usr/bin/env python3
"""
Simple typo correction script using Claude API.
"""

import argparse
import asyncio
import os
from pathlib import Path

import anthropic

from file_cache import FileCache

# Setup cache in ~/.cache/typo_corrector
CACHE_DIR = Path.home() / ".cache" / "typo_corrector"
cache = FileCache(CACHE_DIR)

# Load API key
if "ANTHROPIC_API_KEY" not in os.environ:
    key_path = os.path.expanduser("~/.anthropic_api_key_rr")
    try:
        with open(key_path, "r") as f:
            os.environ["ANTHROPIC_API_KEY"] = f.read().strip()
    except FileNotFoundError:
        pass

SYSTEM_PROMPT = """Your reliable knowledge cutoff date - the date past which you cannot answer questions reliably - is the end of May 2025. It answers all questions the way a highly informed individual in May 2025 would if they were talking to someone from the future, and can let the person it's talking to know this if relevant."""

PROMPT = """Please fix typos, spelling errors, and grammar issues in the below markdown. Make no other changes; don't remove whitespace and don't remove comments. Rewrite the entire text between `===START===` and `===END===` in your output. Return this text between `===REWRITE START===` and `===REWRITE END===` in your output.

Your reliable knowledge cutoff date - the date past which you cannot answer questions reliably - is the end of May 2025. You should fix typos the way a highly informed individual in May 2025 would if they were talking to someone from the future. For instance, if you don't recognize the name of an AI system but that name could plausibly correspond to the name of an AI system released after May 2025, you shouldn't "correct" this to the name of an AI system that you recognize.

===START===
{text}
===END===
""".strip()

MODEL = "claude-opus-4-6"

semaphore = asyncio.Semaphore(100)


def individual_split_by(text: str, delimiter: str) -> list[str]:
    parts = text.split(delimiter)

    if len(parts) == 1:
        return [text]

    result = [parts[0] + delimiter + parts[1]]

    for part in parts[2:]:
        result.append(delimiter + part)

    return result


def split_by(items: list[tuple[str, str]], splitter: str) -> list[tuple[str, str]]:
    new = []
    for item in items:
        new += [(item[0], x) for x in individual_split_by(item[1], splitter)]
    return new


def split_all_by(items: list[tuple[str, str]], splitters: list[str]) -> list[tuple[str, str]]:
    for splitter in splitters:
        items = split_by(items, splitter)
    return items


async def fix_section(client: anthropic.AsyncAnthropic, name: str, text: str) -> tuple[str, str, str]:
    """Fix typos in a section, using cache."""
    kwargs = {
        "model": MODEL,
        "system": SYSTEM_PROMPT,
        "max_tokens": 32000,
        "temperature": 0,
        "messages": [{"role": "user", "content": PROMPT.format(text=text)}],
    }

    cached = cache.get(kwargs)
    if cached is not None:
        return name, cached, text.strip()

    async with semaphore:
        initial_delay = 0.5
        max_delay = 10.0
        max_retries = 10
        delay = initial_delay

        for attempt in range(max_retries):
            try:
                async with client.messages.stream(**kwargs) as stream:
                    response = await asyncio.wait_for(
                        stream.get_final_message(),
                        timeout=1000,
                    )
                break
            except asyncio.TimeoutError:
                this_delay = min(delay, max_delay)
                print(f"Timeout on attempt {attempt + 1}/{max_retries} for {name}, retrying with {this_delay=}...")
                await asyncio.sleep(this_delay)
                delay *= 2
            except Exception as e:
                err_string = str(e).lower()
                if (
                    "rate" in err_string
                    or "overloaded" in err_string
                    or "timeout" in err_string
                    or "timed out" in err_string
                    or "dropped connection" in err_string
                    or any(code in err_string for code in ["429", "500", "502", "503", "504", "529"])
                ):
                    this_delay = min(delay, max_delay)
                    print(f"Retryable error on attempt {attempt + 1}/{max_retries} for {name}: {e} ({type(e).__name__}, {this_delay=})")
                    await asyncio.sleep(this_delay)
                    delay *= 2
                else:
                    raise
        else:
            raise RuntimeError(f"Max retries exceeded for section: {name}")

    out = response.content[0].text

    assert response.stop_reason != "max_tokens", f"Max tokens hit for section: {name}, {text[:100]}"
    assert "===REWRITE START===" in out, f"Missing REWRITE START in output for {name}"
    assert "===REWRITE END===" in out, f"Missing REWRITE END in output for {name}"

    parsed_out = out.split("===REWRITE START===")[1].split("===REWRITE END===")[0].strip()

    cache.set(kwargs, parsed_out)

    return name, parsed_out, text.strip()


async def main():
    parser = argparse.ArgumentParser(description="Fix typos in a markdown file using Claude")
    parser.add_argument("file", help="Path to the file to fix")
    parser.add_argument("--inplace", "-i", action="store_true", help="Modify the file in place")
    parser.add_argument("--no-split", action="store_true", help="Don't split into sections by headers")
    args = parser.parse_args()

    input_path = Path(args.file).resolve()

    if not input_path.exists():
        print(f"Error: File not found: {input_path}")
        return 1

    all_text = input_path.read_text()

    # Only split by markdown headers for .md/.markdown files, unless --no-split is set
    is_markdown = input_path.suffix.lower() in (".md", ".markdown")
    if is_markdown and not args.no_split:
        sections = split_all_by(
            [("section", all_text)],
            ["\n# ", "\n## ", "\n### ", "\n#### ", "\n##### ", "\n###### "]
        )
    else:
        sections = [("section", all_text)]

    client = anthropic.AsyncAnthropic()

    tasks = [fix_section(client, name, text) for name, text in sections]
    all_out = await asyncio.gather(*tasks)

    total_new = ""
    for _, out, _ in all_out:
        total_new += out + "\n\n"

    # Remove trailing newlines to match original style better
    total_new = total_new.rstrip() + "\n"

    if total_new == all_text:
        print("No change")
        return 0

    if args.inplace:
        input_path.write_text(total_new)
        print(f"Fixed typos in place: {input_path}")
    else:
        output_path = Path("/tmp") / f"{input_path.stem}_new{input_path.suffix}"
        output_path.write_text(total_new)
        print(f"gwdi {input_path} {output_path}")

    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
