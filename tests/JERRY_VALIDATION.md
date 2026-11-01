# Jerry source migration validation

Validation date: 2026-10-31. No GitHub push or marketplace publication was performed.

## Offline checks

- Latest complete offline run: **236 tests passed, 87 subtests passed**.
- New source tests: `tests/test_jerry_sources.py`.
- The local-only runner `.cache/run_offline_tests.py` explicitly substitutes
  AstrBot interfaces because the SDK is not installed in this virtual environment.
  HTTP, JSON handling and Pillow are real. This is not an AstrBot runtime test.
- `tests/test_text_utils.py` was excluded on Windows because it uses `time.tzset`.
- The existing concurrent translation pacing test intermittently observed a
  0.031-second interval versus its 0.04-second assertion on Windows. It passed in
  the final full run. No unrelated translation code was changed.
- Python compilation and `_conf_schema.json` parsing passed.
- The skill-referenced `scripts/check_astrbot_plugin.py` is not present in the
  installed skill directory, so that checker was not run.

## Live read-only checks

- Static queries verified equipment model and Chinese names, stratagems, enemies,
  boosters, warbonds, missions, Chinese mechanics overlays and version-specific
  patch-note selection.
- Real task data contains repeated IDs across categories. The adapter follows
  `mission.html`: the final matching task wins.
- Same-title patch-note candidates include version and section identities.
- No MediaWiki supplemental requests or model translation are used by `/wiki`.
- A real 2560x1440 map screenshot was generated in about 12 seconds, with source
  snapshot timestamp `2026-10-31T19:21:12+08:00`.
- Full-size and 640x360 preview images were inspected: Chinese labels and
  territory/supply-line layers are visible; small planet names require zooming
  the full-resolution image on a phone.
- Local samples are in `.cache/jerry_live_map/`; downloaded validation data and
  samples are ignored by Git and are not bundled as plugin assets.

## Server timeout investigation

- The supplied AstrBot 4.29.3 log shows navigation stopping at Playwright's
  default 30-second DOMContentLoaded timeout, before the configured 45-second
  capture budget was exhausted. The local rendering fallback worked.
- Navigation now explicitly uses the configured timeout and waits for document
  commit. Subsequent data, font and layer checks remain mandatory; the outer
  total budget is unchanged. Other page waits also use the configured timeout.
- Failure logs include the exception type, capture stage and whether a proxy
  was configured, without printing the proxy address or credentials.
- Three new tests cover custom navigation/wait budgets, navigation failure
  cleanup and rejection of non-200 document responses. The source test file
  passed 39 tests and 24 subtests.
- Repeat live captures during this investigation did NOT produce a new valid
  screenshot: 45-second attempts timed out, and a 90-second diagnostic attempt
  remained at the war-data stage. A request-traced 45-second attempt received
  the page, scripts and war JSON, then exhausted its budget at Chinese fonts.
  An independent HTTP request returned current JSON with 273 planets in about
  3.8 seconds. These observations do not establish connectivity from the user's
  server or identify a definitive network root cause.
- The earlier successful sample above remains historical evidence only. The
  timeout correction passed offline regression, but screenshot recovery on
  the user's server is not verified.

## Follow-up: blocked scripts and duplicate font faces

- A subsequent server log still reported `stage=war data`. Its settings
  screenshot showed a 233-second budget, but the old log did not establish
  which budget was active in the running plugin.
- A local request trace reproduced stalled MapLibre/tactical script downloads
  before the page issued its war-data request. An HTTP/1.1-only browser
  comparison finished the core script in about seven seconds and then received
  war data. This is a local comparison, not proof of the server's root cause.
- Capture now disables HTTP/2 and QUIC in its independent browser, not the
  Companion browser. It attempts known installed CJK faces using FontFace's
  local sources. Only a successful local face load suppresses the redundant
  remote font request; without a local face, the original request is retained.
- The old FontFaceSet.check condition remained false with one failed remote
  face even though a same-family local face was loaded and the map's style,
  tiles and boot state were ready. Readiness now requires an actually loaded
  SourceHanSans face rather than rejecting that duplicate-face state.
- A new real 2560x1440 capture succeeded in **25.7 seconds**, using snapshot
  `2026-10-31T20:55:50+08:00`. The full-size and 640x360 preview were inspected;
  Chinese labels, territory and supply lines were visible. The source test
  file passed **42 tests and 27 subtests**.
- This live check used system Chrome with the same transport flags; font
  preparation, page readiness and image validation used production code.
  Standard Playwright Chromium and Linux/AstrBot delivery remain unverified.
- Resource diagnostics now distinguish page scripts, war-data response and
  body; retain a bounded set of pending/failed paths without query strings;
  and report actual elapsed time, budget, font source and script error count.
- The first full follow-up run had 235 passes and the existing Windows
  translation pacing failure described above. The complete rerun passed all
  236 tests and 87 subtests. No translation implementation was changed.

## Deployment limitations

- Playwright was installed in the project virtual environment. The bundled
  Chromium download stalled and was stopped without leaving an installer running.
- Live capture used the installed system Chrome in an isolated headless context
  through a local smoke-test override. Production code still uses standard
  Playwright Chromium. Install it and its Linux dependencies in the actual
  AstrBot environment; otherwise `/map` falls back to local rendering.
- No real AstrBot reload, chat delivery, Linux WebGL or platform upload acceptance
  was verified. Those checks require the instance address and locally configured
  API credentials; credentials must not be committed or pasted into chat.
