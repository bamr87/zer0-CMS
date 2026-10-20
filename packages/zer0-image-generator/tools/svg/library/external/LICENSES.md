# External source licenses

Files under this directory are third-party work, kept byte-pristine as downloaded. Per-file provenance lives in `../MANIFEST.json`; this file summarizes each source's license and what it obliges.

| Directory | Source | License | Obligations for reuse/modification |
| --- | --- | --- | --- |
| `feather/` | [feathericons/feather](https://github.com/feathericons/feather) | [MIT](https://github.com/feathericons/feather/blob/master/LICENSE) | Keep license notice with substantial copies. |
| `lucide/` | [lucide-icons/lucide](https://github.com/lucide-icons/lucide) | [ISC](https://github.com/lucide-icons/lucide/blob/main/LICENSE) | Keep license notice with substantial copies. |
| `bootstrap/` | [twbs/icons](https://github.com/twbs/icons) | [MIT](https://github.com/twbs/icons/blob/main/LICENSE) | Keep license notice with substantial copies. |
| `heroicons/` | [tailwindlabs/heroicons](https://github.com/tailwindlabs/heroicons) | [MIT](https://github.com/tailwindlabs/heroicons/blob/master/LICENSE) | Keep license notice with substantial copies. |
| `tabler/` | [tabler/tabler-icons](https://github.com/tabler/tabler-icons) | [MIT](https://github.com/tabler/tabler-icons/blob/main/LICENSE) | Keep license notice with substantial copies. |
| `twemoji/` | [jdecked/twemoji](https://github.com/jdecked/twemoji) | [CC-BY 4.0](https://github.com/jdecked/twemoji/blob/main/LICENSE-GRAPHICS) | Published work using these graphics must credit Twemoji. |
| `openmoji/` | [hfg-gmuend/openmoji](https://github.com/hfg-gmuend/openmoji) | [CC BY-SA 4.0](https://github.com/hfg-gmuend/openmoji/blob/master/LICENSE.txt) | Credit OpenMoji; **derivatives must be shared under CC BY-SA 4.0** — do not fold modified copies into differently-licensed work. |
| `wikimedia/` | [Wikimedia Commons](https://commons.wikimedia.org) | CC0 / Public domain, vetted per file | None; the Commons file page recorded per entry is the provenance trail. |
| `freesvg/` | [FreeSVG.org](https://freesvg.org) via `tools/svg/freesvg.py promote` | CC0 / Public domain (site-wide) | None; files land here only through `promote`, which lints them and records API provenance in the manifest. |

Adding a new source: vet the license first, add a row here, and record the exact license string per file in the manifest. Sources whose license restricts commercial use or forbids modification do not belong in this library.
