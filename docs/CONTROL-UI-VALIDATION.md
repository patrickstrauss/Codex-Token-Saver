# Component control validation

2026-09-20. Validation used the repository source and isolated fixtures, not live routing or user conversations.

The dashboard test suite covers Host/Origin/CSRF rejection, strict component/action payloads, one mutation per click, independent preferences, unavailable runtimes, selected-component health, RTK date windows and lifetime outliers. JavaScript tests execute the shipped scripts.

A browser run against `dashboard/tests/ui_fixture.py` on loopback port 18795 verified:

- Switching RTK Off kept Headroom local output On.
- An unavailable Serena runtime displayed a disabled switch.
- The RTK Today / 7 days selector changed the displayed estimate while retaining lifetime context.
- Update cards for Headroom, RTK and Serena rendered with the correct controls. Laya's staged updater requires the October 8 qualification.
- The console contained no JavaScript errors. The browser tab and fixture server were stopped afterward.

The fixture keeps settings in memory. It never reads real conversations, launches models, changes Codex configuration, or performs library updates. It validates presentation and action wiring; runtime compatibility and restart behavior require separate runtime checks.

Reproduce automated checks with the dashboard virtual environment: `python -m pytest` from `dashboard/`.
