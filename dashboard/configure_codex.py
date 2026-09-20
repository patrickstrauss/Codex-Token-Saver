"""Retired one-shot installer. Importing this module has no side effects."""

if __name__ == "__main__":
    import sys

    print(
        "This legacy configuration script is retired and made no changes. "
        "Codex desktop must keep its normal connection. "
        "Use the repaired bundle in %USERPROFILE%\\CodexTokenSaver and its README "
        "for dashboard startup or optional experimental CLI sessions.",
        file=sys.stderr,
    )
    raise SystemExit(1)
