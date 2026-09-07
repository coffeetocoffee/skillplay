import sys

from .core import cli


def main() -> None:
    # Bare `skillplay` (no args) launches the TUI; subcommands run the CLI.
    if len(sys.argv) > 1:
        # `skillplay exam --skill X` is a TUI subcommand — handled here so it can
        # launch the app directly into a mastery exam.
        if sys.argv[1] == "exam":
            raise SystemExit(cli.run_exam(sys.argv[2:]))
        raise SystemExit(cli.run(sys.argv[1:]))
    from .tui.app import SkillPlayApp

    app = SkillPlayApp()
    try:
        app.run()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
