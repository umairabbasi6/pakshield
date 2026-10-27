# pakshield

Detect, mask and restore Pakistani CNIC numbers in free English/Urdu text
before sending it to an LLM. Zero dependencies, Python 3.10+.

> **Best-effort heuristic tool.** It does not guarantee that all personal
> data is found and is not a regulatory or compliance certification.

## Where it fits
For basic single-string CNIC checks and province lookup, use
[python-stdnum](https://github.com/arthurdejong/python-stdnum)
(`stdnum.pk.cnic`). pakshield targets **free text**: it finds CNICs inside
English/Urdu prose, understands Urdu digits, avoids flagging 13-digit
timestamps and barcodes (unless a CNIC keyword is within 35 characters),
and swaps CNICs for reversible placeholders.
At the time of writing we found no Pakistan recognizer in Microsoft
Presidio; check its current entity list yourself.

## Usage
```python
from pakshield import redact, restore

safe, vault = redact("My CNIC is 37405-8765432-1, please verify.")
# safe == "My CNIC is [CNIC_1], please verify."
reply = call_llm(safe)
print(restore(reply, vault))
```
Other entry points: `scan()` (detections with score and span),
`parse_cnic()` (strict single-string parser), `is_valid_cnic()`.

## How detection works
The 13th digit is gender parity (odd male, even female), **not a checksum**,
so any 13-digit number can look valid. Candidates get an integer score;
the default threshold is 50.

| Form | Score |
|---|---|
| `37405-8765432-1` | 80 |
| same, touching a leading/trailing `-` | 50 |
| `37405 8765432 1`, or mixed/padded separators | 35 |
| 13 bare digits | 20 |

A keyword within 35 characters adds the strongest single boost (boosts do
not stack): strong +30 (`cnic`, `nadra`, `nicop`, `shanakhti`,
`شناختی کارڈ`, `نادرا`), weak +15 (`nic`, `b-form`, `ب فارم`).
Lower `min_score` to be more aggressive.

## Things to know
* A keyword boosts every bare 13-digit number in its window, so a timestamp
  in the same sentence as "CNIC" can be redacted. This favors
  over-redaction; setting `min_score=51` disables bare-number detection
  entirely (bare + strong keyword scores exactly 50).
* Call `redact()` only on **new untrusted input**, never on text that
  already went through the same vault. If the input contains a placeholder
  for an id the vault already allocated, `PlaceholderCollisionError` is
  raised (prevents prompt-injection into `restore()`).
* `restore(fmt="original")` restores the **first-seen** form for every
  occurrence of the same CNIC. Other modes: `"formatted"`, `"canonical"`.
* The masked `repr` of `CNIC`, `Detection` and `RedactionVault` is a
  logging safeguard only. It does not hide your raw input string in
  tracebacks or error-tracker local-variable dumps. Vaults hold real CNICs
  in memory and cannot be pickled.
* `region` is where the card was **first registered**, not where the person
  lives.
* First digit `8` (Azad Kashmir) is accepted by default but **unconfirmed**
  in official sources; python-stdnum's reported range is 1 to 7. Configure
  with `allowed_first_digits`.
* `strict=True` additionally rejects obviously synthetic serials; it is off
  by default because over-redaction is safer than leaking.
* Known limitation: invisible characters *inside* a number (for example
  from broken PDF copy-paste) can prevent detection.
* IBAN, phone, NTN, Pydantic and Presidio integrations are not
  included yet.
