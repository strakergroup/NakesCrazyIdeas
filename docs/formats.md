# Format and capability support

All automated methods remain **provisional**. The initial use profiles are product information and support content. All nine rubric weight profiles are executable, but that is not evidence of validated automation for every purpose, market, language or modality.

| Format | Real extraction and locators | Automated checks | Remaining examinations |
|---|---|---|---|
| Plain text, UTF-8 | Paragraph inventory; exact Unicode code-point offsets; original bytes | Required text and section labels, terminology, source status, model candidate comparisons when deliberately enabled | Factual completeness, source conflicts, task success, human judgment and applicable access/delivery review |
| Markdown, UTF-8 | Original Markdown and paragraph offsets; media references retained | Text, headings and configured rules; optional model comparison | Rendered output, links and interactions always remain manual; embedded images/media create explicit additional gaps |
| Structured product JSON | Parsed object; every scalar item with RFC 6901 JSON pointer; original bytes or canonical object representation | Required fields, nonempty values, explicit expected values, defined unit conversions, configured wording/terms | Field meanings, consuming-system behavior and general rubric judgments; not software correctness/security validation |
| Readable PDF | Text per page and page-relative offsets; complete original file retained | Checks on extracted text only | All page layouts, figures, table relationships, access alternatives, reading order and interactions require manual examination |
| Readable DOCX | Body paragraphs and table cells; stable XML element paths; complete original file retained | Checks on extracted body text only | Headers, footnotes, text boxes, embedded objects, full table meaning, visuals, rendering and delivery/access characteristics require manual examination |
| Scanned/empty-page/encrypted/unreadable PDF; malformed DOCX | Original registered and explicit extraction errors | No full assessment; any readable partial text remains identified | OCR/reliable extraction required before full assessment; release blocked |
| Image, audio, video, presentation, HTML/app interaction and other unsupported formats | Registration/original-byte retention only | No automated assessment | Explicitly incomplete; cannot release through the pilot gate |

Declared audio, video or other unsupported modalities cannot be treated as assessed plain text. Readable documents may receive a complete **combined human and automated** assessment only after the required manual format examinations are recorded with evidence. The service never claims that text extraction established layout/accessibility conformance.

The plan covers criterion judgments, requirements and an extraction audit independently of the model's claim inventory. The owner must review the original to identify missing material before confirming scope. A provider that returns no claims has not proved there are none; the corresponding examination remains unknown pending a human audit.

## Defined numerical equivalence

The deterministic checker handles explicitly defined calendar month/year equivalence, grams/kilograms/milligrams, millimeters/centimeters/meters, and watts/kilowatts. It uses rational arithmetic. Examples include `24 months` = `two years` and `2 kg` = `2000 g`. Brief requirements use JSON pointers such as `/warranty`, with `expected` and optional `unit`.

It does not equate days and calendar months, convert currencies, infer physical tolerances, or treat consumption as cost. Undefined equivalence needs explicit configuration or a justified human review; it must not be silently guessed. Approved terms mean terms required to appear; forbidden terms are case-insensitive word-boundary checks. Mandated wording is an exact, case-sensitive substring check. Their limits are recorded in check reasons and the reviewer guide.

## Pilot intake limits

The service accepts at most 5 MB of original bytes, 200 PDF pages, 200,000 extracted characters, 1,000 extracted items and 3,000 planned examinations per version. DOCX expanded archive size is capped at 30 MB. Limit/extraction failures remain visible rather than silently truncating material. The model adapter refuses context above 80,000 serialized characters and model output above 2 MB. It does not truncate a source pack to make a failing request appear complete.

These limits keep local operation bounded. A production deployment still needs ingress body limits and isolated, resource-limited document parsers. No OCR, speech transcription, image interpretation, video timing assessment, browser accessibility runner, interaction crawler, automatic translation validation or external-link fetching is supplied.
