# Prior art (round 2 research)

What was read, what it says (from search results and project pages, not from the full papers unless stated), and what this repo took from it. Gaps are marked.

## Citation and grounding verification

| Work | Idea | Here |
|---|---|---|
| Anthropic Citations (API `citations`) | Responses carry citation objects with `cited_text` and a location: `char_location` (start/end character index), `page_location`, `content_block_location`, `search_result_location`. Seen through third-party SDK type listings only; the official page was not retrieved. | Same shape of idea: a verbatim quote plus offsets into the text. Difference: the quote here is *checked* against the fetched page; a provider-side citation is trusted to be what the model read. |
| FActScore (Min et al. 2023, arXiv 2305.14251) | Split text into atomic facts; score the share supported by a knowledge source. Precision only. | Not adopted: the LLM supplies one claim per quote. Noted: later work (BAFE, 2025) reports FActScore marking supported facts unsupported, so a score needs a human look, which the report supports. |
| SAFE / LongFact (Wei et al. 2024) | Search-augmented atomic-fact checking; rewrite facts to be self-contained, filter irrelevant ones. About 72% agreement with crowd annotators (secondary summary). | The "claim must be one self-contained sentence copied from the text" rule is the same lesson. |
| Perplexity / Bing-style hover citations | Footnote numbers with a hover card of source and snippet. Not researched in depth. | Already the report design (numbered claims, tooltip, evidence list). |
| Google Fact Check Tools / ClaimReview (schema.org) | A review has `claimReviewed`, a textual rating (`reviewRating.alternateName`), and the claim text must appear on the page. | The tool checks *support by a cited source*, not truth, so it does not emit ClaimReview; the field names are a possible export format later. |
| AIS, ALCE, AttributionBench, CiteEval | Already cited in FACT_CHECKER.md. | Judge asks the in-context question because of them. |

## Deep links to the quote

* WICG Scroll-to-Text Fragment: `#:~:text=[prefix-,]textStart[,textEnd][,-suffix]`; text is percent-decoded, and `-`, `&`, `,` must be percent-encoded; browsers that do not support it ignore the directive. (Details of matching rules beyond the syntax were not retrieved; behaviour was confirmed by opening a generated link in Chromium: scrolled to the quote.) **Adopted**: `jev_factcheck.fragment`, links in the report and `deep_link` in the JSON.
* W3C Web Annotation selectors: `TextQuoteSelector` (`exact`, `prefix`, `suffix`) and `TextPositionSelector` (start/end offsets). The results here already carry the position selector (offsets into the extracted text); `quote` is the exact selector. A future export could write both. Hypothesis anchors with the position first, then fuzzy prefix/suffix, then fuzzy exact text (diff-match-patch / Bitap): the same layered idea as exact, normalised, near.

## Quote matching best practice

Layered, from strict to loose, reporting which layer matched (Hypothesis, and this repo). Never let a fuzzy layer count as "found" without a flag. Kept: numbers and negations get their own status because a similarity score hides them.

## HTML to text

| Option | Notes |
|---|---|
| trafilatura | Project benchmark (750 docs, 2022 run): F-score 0.909 against 0.801 for readability-lxml 0.8.1; the benchmark is by the trafilatura author. It uses readability-lxml and jusText as fallbacks. Needs lxml and several packages. |
| readability-lxml | Port of the Readability algorithm; lower recall in the same benchmark; needs lxml. |
| Hand-rolled (stdlib `html.parser`) | What this repo uses. Zero dependencies, no network, easy to audit. |

Decision: stay dependency-free, because the checker's job is to find a *quote*, and removing more text can only hide quotes; the stdlib extractor now drops hidden text, `nav`, `footer`, `role=navigation|banner|contentinfo`. An article-extraction library would also remove sidebars and boxes that sometimes contain the cited sentence. Revisit as an optional extra (`trafilatura`) if the judge window needs cleaner context; it should then be an *addition* (a second text), because offsets must refer to a text the report stores.

## Not done

Atomic-fact decomposition (FActScore/SAFE), ClaimReview export, OCR for scanned PDFs, a readability extra.
