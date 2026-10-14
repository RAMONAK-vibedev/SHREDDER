# Contributing to SHREDDER

Thanks for your interest in the project! Here's how you can help.

## Ways to contribute

### 🐛 Found a bug?

Open an Issue describing:
- What you were doing.
- What you expected to happen.
- What actually happened.
- Your Windows version and Python version (if running from source).

### 🌐 Improve a translation

330 translations — all machine-generated. **Any native-speaker fix** is welcome!

**How to submit a fix:**
1. Open `assets/locales/<code>.json` (e.g., `de.json` for German).
2. Find the key (e.g., `"shred_button": "VERNICHTEN"`).
3. Fix the value.
4. Open a Pull Request with a description: "Fix <language>: <what changed>".

**Rules:**
- Don't change keys (`"shred_button"`) — only values.
- Don't touch `meta` — that's the language code and name.
- Test it: run `python main.py`, switch to your language, check the UI.

### 💡 Add a new language

1. Copy `assets/locales/en.json` to `<code>.json` (e.g., `sv.json` for Swedish).
2. Replace `meta.code` and `meta.name`.
3. Translate all values in `strings`.
4. Test: the language will appear in the picker.
5. Open a Pull Request.

### 🛠 Code

Before opening a Pull Request:
- Make sure `python -m pyflakes src/*.py main.py` is **empty**.
- Test live: launch, choose a file, destroy it, switch languages.
- Don't add new dependencies without prior discussion.

## Code style

- Python 3.12.
- Indentation: 4 spaces.
- Comments: in English.
- Function and variable names: in English.

## License

By submitting a Pull Request, you agree that your contribution will be licensed under the MIT License (see `LICENSE`).
