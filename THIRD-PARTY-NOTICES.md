# Third-party components

The root MIT license covers original project code only. Third-party code, data,
models and notices retain their own licenses. This source ZIP does not contain
Python runtimes, downloaded wheels, Node, upstream tool binaries or model weights.
The installer downloads pinned versions directly and verifies hashes. Do not
redistribute an installed directory as though it were entirely MIT-licensed.

| Component | License / upstream source |
|---|---|
| Dashboard base | MIT; [Will Lucking's dashboard](https://github.com/Will-Luck/claude-tools-dashboard); notice in `dashboard/LICENSE` |
| Headroom | Apache-2.0; [source](https://github.com/headroomlabs-ai/headroom) |
| RTK | Apache-2.0; [source](https://github.com/rtk-ai/rtk) |
| Serena 2 application | GPL-3.0-or-later; [licensing overview](https://github.com/oraios/serena/blob/main/LICENSE) |
| Serena SolidLSP component | MIT; same upstream; retain its separate notices |
| Playwright CLI / Playwright | Apache-2.0; [source](https://github.com/microsoft/playwright-cli) |
| ast-grep | MIT; [source](https://github.com/ast-grep/ast-grep) |
| Laya | Apache-2.0; [source](https://github.com/NandhaKishorM/laya) |
| Laya multilingual model | Apache-2.0; [pinned model card](https://huggingface.co/convaiinnovations/laya-multilingual/blob/e4e9ddf21a7b1903b7acffd8814ad4307bf63a67/README.md) |
| uv | MIT or Apache-2.0; [source](https://github.com/astral-sh/uv) |
| CPython | PSF and included notices; [source](https://github.com/python/cpython) |
| Node.js | MIT and included third-party notices; [source](https://github.com/nodejs/node) |

Serena remains a separate, unmodified process. Its license is not replaced by
this project's license. The exact 2.0.0 source distribution is
[serena_agent-2.0.0.tar.gz](https://files.pythonhosted.org/packages/74/b9/0d0822226d2bbcc92331d6953fee6c229a8c9f4b2e6ef3caf88c2841c9c0/serena_agent-2.0.0.tar.gz),
SHA-256 `50afdd69f7b114544d2f52deec58a41ad31a328c5a31808adf6f59afdda5d9cf`.
The GPL and MIT component license texts are in that source archive's `LICENSES`
directory. This project does not offer a proprietary license for Serena.

Python dependency versions/hashes are in `packaging/requirements-*.txt`; npm
dependencies are in `packaging/package-lock.json`. Each installed distribution
retains its upstream metadata/licenses in its runtime. Binary archives' notices
are preserved under `tools/licenses`; Node retains its distribution notices.
Models used by optional request compression are downloaded separately by its
setup process; consult their upstream model cards before redistributing weights.

Release qualification generates a runtime inventory. Before distributing
preinstalled runtimes or adding a component, review its exact version's notices
and corresponding-source obligations. An inventory is not a legal compliance
certification.
