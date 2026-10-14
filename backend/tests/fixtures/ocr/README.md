# Synthetic OCR fixtures

These assets were generated for this project's tests on 2026-10-12 with Pillow and ReportLab (test generation tools only). They contain invented text and measurements, not research participant or business data, and may be redistributed with this repository for tests.

- `printed-zh-en.png`: 1654 × 2339 white RGB image, Windows Microsoft YaHei regular/bold font, Chinese/English printed text. Ground truth: `Sample ID: 0012`, `Concentration: 1.20 mg/L`, `Temperature: -2.5 C`, `Result: 12.50%`.
- `mixed-three-pages.pdf`: ReportLab A4 PDF; physical page 1 has a selectable text layer, page 2 embeds the synthetic printed image as a scan, page 3 is blank. Generated source was `script/.runtime/stage03-step08/manual-samples/文字扫描空白混合-合成.pdf`.

The examples validate structure and known individual strings. They do not establish overall OCR accuracy or scientific correctness. Every OCR block must stay unreviewed.
