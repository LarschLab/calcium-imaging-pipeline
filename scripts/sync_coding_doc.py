from pathlib import Path


SETUP_PATH = Path("setupAgents.md")
OUTPUT_PATH = Path("coding.md")
START_MARKER = "<!-- coding.md:start -->"
END_MARKER = "<!-- coding.md:end -->"


def extract_block(text: str) -> str:
    start = text.index(START_MARKER) + len(START_MARKER)
    end = text.index(END_MARKER)
    return text[start:end].strip() + "\n"


def main() -> None:
    setup_text = SETUP_PATH.read_text(encoding="utf-8")
    coding_text = extract_block(setup_text)
    OUTPUT_PATH.write_text(coding_text, encoding="utf-8")


if __name__ == "__main__":
    main()
